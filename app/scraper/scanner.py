import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Category, EventType, Product, ProductEvent, ProductStatus, RemovalReason, ScanRun
from app.db.session import async_session
from app.scraper.categories import ARCHIVE_CATEGORIES, CATEGORIES
from app.scraper.parser import CatalogParser, ScrapedProduct

_scan_lock = asyncio.Lock()
logger = logging.getLogger(__name__)


class CatalogScanner:
    def __init__(self, parser: CatalogParser | None = None) -> None:
        self.parser = parser or CatalogParser()

    async def run(self) -> ScanRun:
        if _scan_lock.locked():
            raise RuntimeError("Сканирование уже выполняется, дождитесь завершения")

        async with _scan_lock:
            return await self._run_locked()

    async def _run_locked(self) -> ScanRun:
        started_at = datetime.now(UTC)
        scan_id = await self._start_scan(started_at)

        totals = {
            "products_found": 0,
            "new_count": 0,
            "removed_count": 0,
            "price_changed_count": 0,
            "sold_count": 0,
            "delisted_count": 0,
        }

        try:
            archive_ids = await self._fetch_archive_ids()
            await self._ensure_categories()

            for category in CATEGORIES:
                scraped = await self.parser.fetch_category(category)
                totals["products_found"] += len({item.external_id for item in scraped})

                async with async_session() as session:
                    db_category = await session.scalar(
                        select(Category).where(Category.slug == category.slug)
                    )
                    if db_category is None:
                        continue

                    new_count, removed_count, price_changed_count, cat_sold, cat_delisted = (
                        await self._sync_category(session, db_category, scraped, archive_ids)
                    )
                    await session.commit()

                totals["new_count"] += new_count
                totals["removed_count"] += removed_count
                totals["price_changed_count"] += price_changed_count
                totals["sold_count"] += cat_sold
                totals["delisted_count"] += cat_delisted

            async with async_session() as session:
                await self._reclassify_removed(session, archive_ids)
                await session.commit()

            return await self._finish_scan(scan_id, totals)
        except Exception as exc:
            await self._finish_scan(scan_id, totals, error=str(exc))
            raise

    async def _start_scan(self, started_at: datetime) -> int:
        async with async_session() as session:
            scan = ScanRun(started_at=started_at)
            session.add(scan)
            await session.commit()
            await session.refresh(scan)
            return scan.id

    async def _finish_scan(
        self,
        scan_id: int,
        totals: dict[str, int],
        *,
        error: str | None = None,
    ) -> ScanRun:
        async with async_session() as session:
            scan = await session.get(ScanRun, scan_id)
            if scan is None:
                raise RuntimeError(f"ScanRun {scan_id} not found")

            scan.products_found = totals["products_found"]
            scan.new_count = totals["new_count"]
            scan.removed_count = totals["removed_count"]
            scan.sold_count = totals["sold_count"]
            scan.delisted_count = totals["delisted_count"]
            scan.price_changed_count = totals["price_changed_count"]
            scan.finished_at = datetime.now(UTC)
            scan.error = error
            await session.commit()
            await session.refresh(scan)
            return scan

    async def _fetch_archive_ids(self) -> set[str]:
        archive_ids: set[str] = set()
        for category in ARCHIVE_CATEGORIES:
            scraped = await self.parser.fetch_category(category)
            ids = {item.external_id for item in scraped}
            archive_ids.update(ids)
            logger.info("Архив %s: %s позиций", category.name, len(ids))
        logger.info("Всего в архивах: %s уникальных URL", len(archive_ids))
        return archive_ids

    async def _ensure_categories(self) -> None:
        async with async_session() as session:
            for category in CATEGORIES:
                stmt = (
                    insert(Category)
                    .values(
                        slug=category.slug,
                        name=category.name,
                        url_path=category.url_path,
                    )
                    .on_conflict_do_nothing(index_elements=["slug"])
                )
                await session.execute(stmt)
            await session.commit()

    async def _sync_category(
        self,
        session: AsyncSession,
        category: Category,
        scraped: list[ScrapedProduct],
        archive_ids: set[str],
    ) -> tuple[int, int, int, int, int]:
        now = datetime.now(UTC)
        scraped_map = {item.external_id: item for item in scraped}
        seen_ids = set(scraped_map)

        result = await session.execute(
            select(Product).where(
                Product.category_id == category.id,
                Product.status == ProductStatus.ACTIVE,
            )
        )
        active_products = {product.external_id: product for product in result.scalars()}

        new_count = 0
        removed_count = 0
        price_changed_count = 0
        sold_removed = 0
        delisted_removed = 0

        for external_id, item in scraped_map.items():
            product = active_products.get(external_id)
            if product is None:
                restored = await session.scalar(
                    select(Product).where(Product.external_id == external_id)
                )
                if restored:
                    if restored.removal_reason == RemovalReason.SOLD.value:
                        logger.warning(
                            "Проданный товар снова на витрине (тот же URL): %s — не восстанавливаем",
                            external_id,
                        )
                        continue

                    product = restored
                    product.status = ProductStatus.ACTIVE
                    product.removed_at = None
                    product.removal_reason = None
                    product.last_seen_at = now
                    self._apply_fields(product, item)
                    session.add(
                        ProductEvent(product_id=product.id, event_type=EventType.APPEARED)
                    )
                    new_count += 1
                else:
                    product = Product(
                        external_id=item.external_id,
                        category_id=category.id,
                        brand=item.brand,
                        title=item.title,
                        reference=item.reference,
                        condition=item.condition,
                        price_usd=item.price_usd,
                        price_on_request=item.price_on_request,
                        is_reserved=item.is_reserved,
                        is_vip=item.is_vip,
                        tags=item.tags,
                        url=item.url,
                        first_seen_at=now,
                        last_seen_at=now,
                        status=ProductStatus.ACTIVE,
                    )
                    session.add(product)
                    await session.flush()
                    session.add(
                        ProductEvent(product_id=product.id, event_type=EventType.APPEARED)
                    )
                    new_count += 1
                continue

            product.last_seen_at = now
            price_changed_count += self._update_existing(session, product, item)

        for external_id, product in active_products.items():
            if external_id in seen_ids:
                continue

            product.status = ProductStatus.REMOVED
            product.removed_at = now
            product.removal_reason = self._resolve_removal_reason(external_id, archive_ids)
            if product.removal_reason == RemovalReason.SOLD.value:
                sold_removed += 1
            else:
                delisted_removed += 1
            session.add(
                ProductEvent(product_id=product.id, event_type=EventType.REMOVED)
            )
            removed_count += 1

        await session.flush()
        return new_count, removed_count, price_changed_count, sold_removed, delisted_removed

    async def _reclassify_removed(self, session: AsyncSession, archive_ids: set[str]) -> None:
        result = await session.execute(
            select(Product).where(Product.status == ProductStatus.REMOVED)
        )

        for product in result.scalars():
            if product.removal_reason == RemovalReason.SOLD.value:
                continue
            if product.external_id in archive_ids:
                product.removal_reason = RemovalReason.SOLD.value

        await session.flush()

    def _resolve_removal_reason(self, external_id: str, archive_ids: set[str]) -> str:
        if external_id in archive_ids:
            return RemovalReason.SOLD.value
        return RemovalReason.DELISTED.value

    def _update_existing(self, session: AsyncSession, product: Product, item: ScrapedProduct) -> int:
        changes = 0

        old_price = float(product.price_usd) if product.price_usd is not None else None
        new_price = item.price_usd
        old_reserved = product.is_reserved
        new_reserved = item.is_reserved

        self._apply_fields(product, item)

        if old_price != new_price and not item.price_on_request:
            session.add(
                ProductEvent(
                    product_id=product.id,
                    event_type=EventType.PRICE_CHANGED,
                    old_price=old_price,
                    new_price=new_price,
                )
            )
            changes += 1

        if old_reserved != new_reserved:
            session.add(
                ProductEvent(
                    product_id=product.id,
                    event_type=EventType.RESERVED if new_reserved else EventType.UNRESERVED,
                )
            )

        return changes

    def _apply_fields(self, product: Product, item: ScrapedProduct) -> None:
        product.brand = item.brand
        product.title = item.title
        product.reference = item.reference
        product.condition = item.condition
        product.price_usd = item.price_usd
        product.price_on_request = item.price_on_request
        product.is_reserved = item.is_reserved
        product.is_vip = item.is_vip
        product.tags = item.tags
        product.url = item.url
