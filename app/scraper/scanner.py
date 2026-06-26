import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Category, EventType, Product, ProductEvent, ProductStatus, RemovalReason, ScanRun
from app.scraper.categories import ARCHIVE_CATEGORIES, CATEGORIES
from app.scraper.parser import CatalogParser, ScrapedProduct

_scan_lock = asyncio.Lock()
logger = logging.getLogger(__name__)


class CatalogScanner:
    def __init__(self, parser: CatalogParser | None = None) -> None:
        self.parser = parser or CatalogParser()

    async def run(self, session: AsyncSession) -> ScanRun:
        if _scan_lock.locked():
            raise RuntimeError("Сканирование уже выполняется, дождитесь завершения")

        async with _scan_lock:
            return await self._run_locked(session)

    async def _run_locked(self, session: AsyncSession) -> ScanRun:
        started_at = datetime.now(UTC)
        scan = ScanRun(started_at=started_at)
        session.add(scan)
        await session.flush()

        total_found = 0
        total_new = 0
        total_removed = 0
        total_price_changed = 0
        sold_removed = 0
        delisted_removed = 0

        try:
            await self._ensure_categories(session)
            archive_ids = await self._fetch_archive_ids()

            for category in CATEGORIES:
                db_category = await session.scalar(select(Category).where(Category.slug == category.slug))
                if db_category is None:
                    continue

                scraped = await self.parser.fetch_category(category)
                total_found += len({item.external_id for item in scraped})

                new_count, removed_count, price_changed_count, cat_sold, cat_delisted = (
                    await self._sync_category(session, db_category, scraped, archive_ids)
                )
                total_new += new_count
                total_removed += removed_count
                total_price_changed += price_changed_count
                sold_removed += cat_sold
                delisted_removed += cat_delisted

            await self._reclassify_removed(session, archive_ids)

            scan.products_found = total_found
            scan.new_count = total_new
            scan.removed_count = total_removed
            scan.sold_count = sold_removed
            scan.delisted_count = delisted_removed
            scan.price_changed_count = total_price_changed
            scan.finished_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(scan)
            return scan
        except Exception as exc:
            await session.rollback()
            error_scan = ScanRun(
                started_at=started_at,
                finished_at=datetime.now(UTC),
                error=str(exc),
            )
            session.add(error_scan)
            await session.commit()
            raise

    async def _fetch_archive_ids(self) -> set[str]:
        archive_ids: set[str] = set()
        for category in ARCHIVE_CATEGORIES:
            scraped = await self.parser.fetch_category(category)
            ids = {item.external_id for item in scraped}
            archive_ids.update(ids)
            logger.info("Архив %s: %s позиций", category.name, len(ids))
        logger.info("Всего в архивах: %s уникальных URL", len(archive_ids))
        return archive_ids

    async def _ensure_categories(self, session: AsyncSession) -> None:
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
        await session.flush()

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
                        # Проданный лот с этим URL остаётся в истории продаж.
                        # Новый завоз той же модели — всегда новый URL и новая запись в БД.
                        logger.warning(
                            "Проданный товар снова на витрине (тот же URL): %s — не восстанавливаем",
                            external_id,
                        )
                        continue

                    # Тот же URL — тот же лот (вернули после снятия с витрины).
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
                # Продажа не отменяется: новый завоз = новый URL, старая запись остаётся sold.
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
