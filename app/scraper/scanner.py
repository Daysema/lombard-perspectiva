import asyncio
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Category, EventType, Product, ProductEvent, ProductStatus, ScanRun
from app.scraper.categories import CATEGORIES
from app.scraper.parser import CatalogParser, ScrapedProduct

_scan_lock = asyncio.Lock()


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

        try:
            await self._ensure_categories(session)

            for category in CATEGORIES:
                db_category = await session.scalar(select(Category).where(Category.slug == category.slug))
                if db_category is None:
                    continue

                scraped = await self.parser.fetch_category(category)
                total_found += len(scraped)

                new_count, removed_count, price_changed_count = await self._sync_category(
                    session, db_category, scraped
                )
                total_new += new_count
                total_removed += removed_count
                total_price_changed += price_changed_count

            scan.products_found = total_found
            scan.new_count = total_new
            scan.removed_count = total_removed
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
    ) -> tuple[int, int, int]:
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

        for external_id, item in scraped_map.items():
            product = active_products.get(external_id)
            if product is None:
                restored = await session.scalar(
                    select(Product).where(Product.external_id == external_id)
                )
                if restored:
                    product = restored
                    product.status = ProductStatus.ACTIVE
                    product.removed_at = None
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
            session.add(
                ProductEvent(product_id=product.id, event_type=EventType.REMOVED)
            )
            removed_count += 1

        await session.flush()
        return new_count, removed_count, price_changed_count

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
