from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.db.models import Category, Product, ProductStatus, RemovalReason, ScanRun


@dataclass
class Period:
    days: int

    @property
    def start(self) -> datetime:
        return datetime.now(UTC) - timedelta(days=self.days)

    @property
    def label(self) -> str:
        if self.days == 1:
            return "за сутки"
        if self.days == 7:
            return "за неделю"
        if self.days == 30:
            return "за месяц"
        return f"за {self.days} дн."


PRICE_BUCKETS = [
    ("до $5 000", 0, 5000),
    ("$5 000 – $15 000", 5000, 15000),
    ("$15 000 – $50 000", 15000, 50000),
    ("$50 000 – $100 000", 50000, 100000),
    ("свыше $100 000", 100000, None),
]


class ReportService:
    async def get_last_scan(self, session: AsyncSession) -> ScanRun | None:
        return await session.scalar(select(ScanRun).order_by(ScanRun.id.desc()).limit(1))

    async def sold_products(self, session: AsyncSession, period: Period) -> list[Product]:
        result = await session.execute(
            select(Product)
            .options(joinedload(Product.category))
            .where(
                Product.status == ProductStatus.REMOVED,
                Product.removal_reason == RemovalReason.SOLD.value,
                Product.removed_at >= period.start,
            )
            .order_by(Product.removed_at.desc())
        )
        return list(result.scalars())

    async def delisted_products(self, session: AsyncSession, period: Period) -> list[Product]:
        result = await session.execute(
            select(Product)
            .options(joinedload(Product.category))
            .where(
                Product.status == ProductStatus.REMOVED,
                Product.removal_reason == RemovalReason.DELISTED.value,
                Product.removed_at >= period.start,
            )
            .order_by(Product.removed_at.desc())
        )
        return list(result.scalars())

    async def new_products(self, session: AsyncSession, period: Period) -> list[Product]:
        result = await session.execute(
            select(Product)
            .options(joinedload(Product.category))
            .where(Product.first_seen_at >= period.start)
            .order_by(Product.first_seen_at.desc())
        )
        return list(result.scalars())

    async def top_brands(self, session: AsyncSession, period: Period, limit: int = 10) -> list[tuple[str, int]]:
        result = await session.execute(
            select(Product.brand, func.count(Product.id))
            .where(
                Product.status == ProductStatus.REMOVED,
                Product.removal_reason == RemovalReason.SOLD.value,
                Product.removed_at >= period.start,
                Product.brand != "",
            )
            .group_by(Product.brand)
            .order_by(func.count(Product.id).desc())
            .limit(limit)
        )
        return [(brand, count) for brand, count in result.all()]

    async def fastest_selling_brands(
        self, session: AsyncSession, period: Period, limit: int = 10
    ) -> list[tuple[str, float, int]]:
        result = await session.execute(
            select(Product)
            .where(
                Product.status == ProductStatus.REMOVED,
                Product.removal_reason == RemovalReason.SOLD.value,
                Product.removed_at >= period.start,
                Product.brand != "",
            )
        )
        products = list(result.scalars())

        brand_days: dict[str, list[float]] = defaultdict(list)
        for product in products:
            if product.removed_at is None:
                continue
            days = (product.removed_at - product.first_seen_at).total_seconds() / 86400
            brand_days[product.brand].append(max(days, 0))

        averages = [
            (brand, sum(values) / len(values), len(values))
            for brand, values in brand_days.items()
            if values
        ]
        averages.sort(key=lambda item: item[1])
        return averages[:limit]

    async def brand_stats(
        self, session: AsyncSession, brand: str, period: Period, *, exact: bool = False
    ) -> dict:
        brand_filter = Product.brand == brand if exact else Product.brand.ilike(f"%{brand}%")

        sold_result = await session.execute(
            select(Product)
            .options(joinedload(Product.category))
            .where(
                brand_filter,
                Product.status == ProductStatus.REMOVED,
                Product.removal_reason == RemovalReason.SOLD.value,
                Product.removed_at >= period.start,
            )
            .order_by(Product.removed_at.desc())
        )
        sold = list(sold_result.scalars())

        active_result = await session.execute(
            select(func.count(Product.id)).where(
                brand_filter,
                Product.status == ProductStatus.ACTIVE,
            )
        )
        active_count = active_result.scalar_one()

        prices = [float(p.price_usd) for p in sold if p.price_usd is not None]
        avg_price = sum(prices) / len(prices) if prices else None

        resolved_brand = sold[0].brand if sold else brand
        return {
            "brand": resolved_brand,
            "sold_count": len(sold),
            "active_count": active_count,
            "avg_price": avg_price,
            "sold": sold,
        }

    async def distinct_brands(self, session: AsyncSession) -> list[str]:
        result = await session.execute(
            select(Product.brand).where(Product.brand != "").distinct()
        )
        return [row[0] for row in result.all()]

    async def price_distribution(self, session: AsyncSession, period: Period) -> dict[str, int]:
        products = await self.sold_products(session, period)
        counter: Counter[str] = Counter()
        counter["Цена по запросу"] = 0

        for product in products:
            if product.price_on_request or product.price_usd is None:
                counter["Цена по запросу"] += 1
                continue

            price = float(product.price_usd)
            for label, low, high in PRICE_BUCKETS:
                if high is None and price >= low:
                    counter[label] += 1
                    break
                if high is not None and low <= price < high:
                    counter[label] += 1
                    break

        return dict(counter)

    async def summary(self, session: AsyncSession, period: Period) -> dict:
        sold = await self.sold_products(session, period)
        delisted = await self.delisted_products(session, period)
        new_items = await self.new_products(session, period)
        top_brands = await self.top_brands(session, period, limit=5)
        price_dist = await self.price_distribution(session, period)
        fast_brands = await self.fastest_selling_brands(session, period, limit=5)

        by_category: Counter[str] = Counter()
        for product in sold:
            by_category[product.category.name] += 1

        return {
            "period": period,
            "sold": sold,
            "delisted": delisted,
            "new_items": new_items,
            "top_brands": top_brands,
            "price_dist": price_dist,
            "fast_brands": fast_brands,
            "by_category": dict(by_category),
        }

    async def active_count(self, session: AsyncSession) -> int:
        result = await session.execute(
            select(func.count(Product.id)).where(Product.status == ProductStatus.ACTIVE)
        )
        return result.scalar_one()


report_service = ReportService()
