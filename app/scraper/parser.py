import asyncio
import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.scraper.categories import CatalogCategory

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
PRICE_ON_REQUEST_MARKERS = ("цена по запросу", "price on request")
_RETRYABLE_ERRORS = (
    httpx.ReadTimeout,
    httpx.ConnectTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.NetworkError,
)


@dataclass
class ScrapedProduct:
    external_id: str
    brand: str
    title: str
    reference: str | None
    condition: str | None
    price_usd: float | None
    price_on_request: bool
    is_reserved: bool
    is_vip: bool
    tags: str | None
    url: str


class CatalogParser:
    def __init__(self, base_url: str | None = None, delay: float | None = None) -> None:
        self.base_url = (base_url or settings.site_base_url).rstrip("/")
        self.delay = delay if delay is not None else settings.request_delay_seconds
        self.timeout = httpx.Timeout(
            connect=30.0,
            read=settings.http_timeout_seconds,
            write=30.0,
            pool=30.0,
        )
        self.max_retries = settings.http_max_retries
        self._prefer_proxy = False

    def _client_kwargs(self, proxy: str | None = None) -> dict:
        kwargs: dict = {
            "headers": {"User-Agent": USER_AGENT},
            "timeout": self.timeout,
            "follow_redirects": True,
        }
        if proxy:
            kwargs["proxy"] = proxy
        return kwargs

    async def _get_with_retry(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return await client.get(url)
            except _RETRYABLE_ERRORS as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                wait = 2**attempt
                logger.warning(
                    "Сетевая ошибка (%s) для %s, повтор %s/%s через %s с",
                    type(exc).__name__,
                    url,
                    attempt,
                    self.max_retries,
                    wait,
                )
                await asyncio.sleep(wait)
        assert last_error is not None
        raise last_error

    async def _fetch_url(self, url: str) -> httpx.Response:
        routes: list[tuple[str | None, str]] = []
        if self._prefer_proxy and settings.http_proxy:
            routes = [(settings.http_proxy, "через прокси")]
        else:
            routes = [(None, "напрямую")]
            if settings.http_proxy:
                routes.append((settings.http_proxy, "через прокси"))

        last_error: Exception | None = None
        for index, (proxy, label) in enumerate(routes):
            try:
                async with httpx.AsyncClient(**self._client_kwargs(proxy)) as client:
                    response = await self._get_with_retry(client, url)
                if proxy is not None:
                    self._prefer_proxy = True
                return response
            except _RETRYABLE_ERRORS as exc:
                last_error = exc
                if index < len(routes) - 1:
                    logger.warning(
                        "Запрос не удался %s (%s), пробую %s",
                        label,
                        type(exc).__name__,
                        routes[index + 1][1],
                    )
                    continue
                raise

        assert last_error is not None
        raise last_error

    async def fetch_category(self, category: CatalogCategory) -> list[ScrapedProduct]:
        products: list[ScrapedProduct] = []
        page = 1

        while True:
            url = f"{self.base_url}/{category.url_path}/"
            if page > 1:
                url = f"{url}?page={page}"

            response = await self._fetch_url(url)
            if response.status_code == 404 and page > 1:
                break
            response.raise_for_status()

            page_products = await asyncio.to_thread(self._parse_page, response.text)
            if not page_products:
                break

            products.extend(page_products)
            last_page = await asyncio.to_thread(
                self._extract_last_page, response.text, category.url_path
            )
            if page >= last_page:
                break

            page += 1
            await asyncio.sleep(self.delay)

        return products

    def _parse_page(self, html: str) -> list[ScrapedProduct]:
        soup = BeautifulSoup(html, "lxml")
        items = soup.select("a.product-list-item.catalog-item")
        products: list[ScrapedProduct] = []

        for item in items:
            href = item.get("href")
            if not href:
                continue

            url = urljoin(self.base_url, href)
            external_id = href.rstrip("/")

            brand_el = item.select_one(".item-name")
            title_el = item.select_one(".catalog-item--subtitle p")
            condition_el = item.select_one(".status-used__tooltip")
            price_el = item.select_one(".item-price--text")
            ref_el = item.select_one(".catalog-item--ref p")
            reserved_block = item.select_one(".reserved-text--block")

            brand = _clean(brand_el.get_text()) if brand_el else ""
            title = _clean(title_el.get_text()) if title_el else ""
            condition = _clean(condition_el.get_text()) if condition_el else None

            price_text = _clean(price_el.get_text()) if price_el else ""
            price_usd, price_on_request = _parse_price(price_text)

            reference = None
            if ref_el:
                ref_text = _clean(ref_el.get_text())
                reference = re.sub(r"^Референс:\s*", "", ref_text, flags=re.IGNORECASE).strip() or None

            reserved_text = _clean(reserved_block.get_text()) if reserved_block else ""
            is_reserved = "резерв" in reserved_text.lower() or "reserve" in reserved_text.lower()

            badges = [_clean(node.get_text()) for node in item.select(".badge-element div")]
            tags = ", ".join(badge for badge in badges if badge) or None
            is_vip = any("vip" in badge.lower() for badge in badges)

            products.append(
                ScrapedProduct(
                    external_id=external_id,
                    brand=brand,
                    title=title,
                    reference=reference,
                    condition=condition,
                    price_usd=price_usd,
                    price_on_request=price_on_request,
                    is_reserved=is_reserved,
                    is_vip=is_vip,
                    tags=tags,
                    url=url,
                )
            )

        return products

    def _extract_last_page(self, html: str, url_path: str) -> int:
        soup = BeautifulSoup(html, "lxml")
        pages: list[int] = []

        for link in soup.select("a.paginate-link"):
            href = link.get("href", "")
            if url_path not in href:
                continue
            match = re.search(r"[?&]page=(\d+)", href)
            if match:
                pages.append(int(match.group(1)))

        return max(pages) if pages else 1


def _clean(value: str) -> str:
    return " ".join(value.split())


def _parse_price(text: str) -> tuple[float | None, bool]:
    lowered = text.lower()
    if not text or any(marker in lowered for marker in PRICE_ON_REQUEST_MARKERS):
        return None, True

    numbers = re.findall(r"[\d\s]+", text.replace(",", ""))
    parsed: list[float] = []
    for number in numbers:
        cleaned = number.replace(" ", "").strip()
        if not cleaned:
            continue
        try:
            parsed.append(float(Decimal(cleaned)))
        except InvalidOperation:
            continue

    if not parsed:
        return None, True

    return parsed[0], False
