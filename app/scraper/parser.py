import asyncio
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.scraper.categories import CatalogCategory

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
PRICE_ON_REQUEST_MARKERS = ("цена по запросу", "price on request")


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

    async def fetch_category(self, category: CatalogCategory) -> list[ScrapedProduct]:
        products: list[ScrapedProduct] = []
        page = 1

        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=60.0,
            follow_redirects=True,
        ) as client:
            while True:
                url = f"{self.base_url}/{category.url_path}/"
                if page > 1:
                    url = f"{url}?page={page}"

                response = await client.get(url)
                response.raise_for_status()

                page_products = self._parse_page(response.text)
                if not page_products:
                    break

                products.extend(page_products)
                last_page = self._extract_last_page(response.text)
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

    def _extract_last_page(self, html: str) -> int:
        soup = BeautifulSoup(html, "lxml")
        pages: list[int] = []

        for link in soup.select("a.paginate-link"):
            match = re.search(r"[?&]page=(\d+)", link.get("href", ""))
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
