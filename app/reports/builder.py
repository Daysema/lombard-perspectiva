import html
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.config import settings
from app.db.models import Product, ScanRun
from app.reports.service import PRICE_BUCKETS, Period

TELEGRAM_MESSAGE_LIMIT = 4000
ITEMS_PER_PAGE = 12


def paginate_list(items: list, page: int, per_page: int = ITEMS_PER_PAGE) -> tuple[list, int, int]:
    total_pages = max(1, (len(items) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    return items[start : start + per_page], page, total_pages


def format_msk(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    msk = dt.astimezone(ZoneInfo(settings.timezone))
    return msk.strftime("%d.%m.%Y %H:%M") + " МСК"


def format_money(value: float | None) -> str:
    if value is None:
        return "по запросу"
    return f"${value:,.0f}".replace(",", " ")


def _esc(value: str) -> str:
    return html.escape(value, quote=False)


def format_product_line(product: Product, include_category: bool = False) -> str:
    price = format_money(float(product.price_usd) if product.price_usd is not None else None)
    if product.price_on_request:
        price = "по запросу"

    title = _esc(f"{product.brand} {product.title}".strip())
    ref = f" ({_esc(product.reference)})" if product.reference else ""
    category = (
        f" [{_esc(product.category.name)}]"
        if include_category and product.category
        else ""
    )
    return f"• {title}{ref}{category} — {price}"


def build_help_text() -> str:
    return (
        "🕵️ <b>Мониторинг lombard-perspectiva.ru</b>\n\n"
        "Выберите раздел в меню ниже.\n\n"
        "Период по умолчанию — 7 дней. Другой период: <code>/sold 30</code>\n"
        "Статистика по бренду: <code>/stats Rolex 30</code>\n\n"
        "Автосканирование: 00:00 и 12:00 МСК.\n"
        "Автоотчёты: ежедневно, еженедельно, ежемесячно.\n\n"
        "ℹ️ Учёт по URL карточки на сайте. Новый завоз = новый URL."
    )


def build_status_text(scan: ScanRun | None, active_count: int) -> str:
    if scan is None:
        return "Сканирование ещё не выполнялось."

    if scan.finished_at:
        finished = format_msk(scan.finished_at)
    elif scan.started_at:
        finished = f"в процессе (начато {format_msk(scan.started_at)})"
    else:
        finished = "в процессе"

    lines = [
        "📡 <b>Статус мониторинга</b>",
        f"Последнее сканирование: {finished}",
        f"Товаров в каталоге: {active_count}",
        f"Найдено при скане: {scan.products_found}",
        f"Новых: {scan.new_count}",
        f"Ушло с витрины: {scan.removed_count}",
        f"├ Продано (архив): {scan.sold_count}",
        f"└ Снято с витрины: {scan.delisted_count}",
        f"Изменений цены: {scan.price_changed_count}",
    ]
    if scan.error:
        lines.append(f"⚠️ Ошибка: {scan.error}")
    return "\n".join(lines)


def build_sold_report(products: list[Product], period: Period, page: int = 0) -> tuple[str, int, int]:
    header = f"✅ <b>Продано {period.label}</b> (в архиве на сайте): {len(products)} шт.\n"
    if not products:
        return header + "\nНет данных за выбранный период.", 0, 1

    page_items, page, total_pages = paginate_list(products, page)
    lines = [header]
    if total_pages > 1:
        lines.append(f"📄 Страница {page + 1} из {total_pages}\n")
    for product in page_items:
        removed = product.removed_at.strftime("%d.%m") if product.removed_at else "?"
        lines.append(f"{format_product_line(product, include_category=True)} — {removed}")
    return "\n".join(lines), page, total_pages


def build_delisted_report(products: list[Product], period: Period, page: int = 0) -> tuple[str, int, int]:
    header = f"📤 <b>Снято с витрины {period.label}</b> (нет в архиве): {len(products)} шт.\n"
    if not products:
        return header + "\nНет данных за выбранный период.", 0, 1

    page_items, page, total_pages = paginate_list(products, page)
    lines = [header]
    if total_pages > 1:
        lines.append(f"📄 Страница {page + 1} из {total_pages}\n")
    for product in page_items:
        removed = product.removed_at.strftime("%d.%m") if product.removed_at else "?"
        lines.append(f"{format_product_line(product, include_category=True)} — {removed}")
    return "\n".join(lines), page, total_pages


def build_new_report(products: list[Product], period: Period, page: int = 0) -> tuple[str, int, int]:
    header = f"🆕 <b>Новые поступления {period.label}</b>: {len(products)} шт.\n"
    if not products:
        return header + "\nНет новых товаров за выбранный период.", 0, 1

    page_items, page, total_pages = paginate_list(products, page)
    lines = [header]
    if total_pages > 1:
        lines.append(f"📄 Страница {page + 1} из {total_pages}\n")
    for product in page_items:
        appeared = product.first_seen_at.strftime("%d.%m") if product.first_seen_at else "?"
        lines.append(f"{format_product_line(product, include_category=True)} — {appeared}")
    return "\n".join(lines), page, total_pages


def build_top_brands_header(period: Period) -> str:
    return f"🏆 <b>Топ брендов по продажам {period.label}</b>\n\nВыберите бренд:"


def build_top_brands_report(brands: list[tuple[str, int]], period: Period) -> str:
    lines = [build_top_brands_header(period)]
    if not brands:
        lines.append("\nНет данных.")
    return "\n".join(lines)


def build_fast_brands_header(period: Period) -> str:
    return f"🔥 <b>Ходовые бренды {period.label}</b> (среднее время на сайте)\n\nВыберите бренд:"


def build_fast_brands_report(brands: list[tuple[str, float, int]], period: Period) -> str:
    lines = [build_fast_brands_header(period)]
    if not brands:
        lines.append("\nНет данных.")
    return "\n".join(lines)


def _days_on_site(product: Product) -> float | None:
    if product.removed_at is None or product.first_seen_at is None:
        return None
    return max((product.removed_at - product.first_seen_at).total_seconds() / 86400, 0)


def build_brand_stats_report(
    stats: dict,
    period: Period,
    page: int = 0,
    *,
    show_time_on_site: bool = False,
) -> tuple[str, int, int]:
    brand = _esc(stats["brand"])
    icon = "🔥" if show_time_on_site else "📊"
    title = "Ходовой бренд" if show_time_on_site else "Статистика"
    lines = [
        f"{icon} <b>{title}: {brand}</b> ({period.label})",
        f"Продано: {stats['sold_count']} шт.",
        f"Сейчас в каталоге: {stats['active_count']} шт.",
    ]
    if stats.get("avg_days_on_site") is not None:
        lines.append(f"Среднее время на сайте: {stats['avg_days_on_site']:.1f} дн.")
    if stats["avg_price"] is not None:
        lines.append(f"Средняя цена проданного: {format_money(stats['avg_price'])}")

    sold: list[Product] = stats["sold"]
    total_pages = 1
    if sold:
        list_title = "Проданные позиции" if show_time_on_site else f"Продано {period.label}"
        lines.append(f"\n<b>{list_title}:</b>")
        page_items, page, total_pages = paginate_list(sold, page)
        if total_pages > 1:
            lines.append(f"📄 Страница {page + 1} из {total_pages}\n")
        for product in page_items:
            removed = product.removed_at.strftime("%d.%m") if product.removed_at else "?"
            line = f"{format_product_line(product, include_category=True)} — {removed}"
            if show_time_on_site:
                days = _days_on_site(product)
                if days is not None:
                    line += f", {days:.1f} дн. на сайте"
            lines.append(line)
    return "\n".join(lines), page, total_pages


def build_price_report(distribution: dict[str, int], period: Period) -> str:
    lines = [f"💰 <b>Ценовые сегменты проданного {period.label}</b>"]
    if not distribution:
        lines.append("\nНет данных.")
        return "\n".join(lines)

    ordered_labels = [label for label, _, _ in PRICE_BUCKETS] + ["Цена по запросу"]
    for label in ordered_labels:
        count = distribution.get(label, 0)
        if count:
            lines.append(f"• {label}: {count} шт.")
    return "\n".join(lines)


def build_summary_report(data: dict) -> str:
    period: Period = data["period"]
    sold: list[Product] = data["sold"]
    delisted: list[Product] = data["delisted"]
    new_items: list[Product] = data["new_items"]
    top_brands: list[tuple[str, int]] = data["top_brands"]
    price_dist: dict[str, int] = data["price_dist"]
    fast_brands: list[tuple[str, float, int]] = data["fast_brands"]
    by_category: dict[str, int] = data["by_category"]

    lines = [
        f"📈 <b>Сводка {period.label}</b>",
        f"Дата: {datetime.now().strftime('%d.%m.%Y')}",
        "",
        f"Продано (архив): <b>{len(sold)}</b> шт.",
        f"Снято с витрины: <b>{len(delisted)}</b> шт.",
        f"Новых поступлений: <b>{len(new_items)}</b> шт.",
    ]

    if by_category:
        lines.append("\n<b>По категориям:</b>")
        for name, count in sorted(by_category.items(), key=lambda item: item[1], reverse=True):
            lines.append(f"• {_esc(name)}: {count}")

    if top_brands:
        lines.append("\n<b>Топ брендов:</b>")
        for brand, count in top_brands:
            lines.append(f"• {_esc(brand)}: {count}")

    if fast_brands:
        lines.append("\n<b>Быстрее всего уходят:</b>")
        for brand, avg_days, count in fast_brands[:3]:
            lines.append(f"• {_esc(brand)}: {avg_days:.1f} дн. ({count} шт.)")

    if price_dist:
        lines.append("\n<b>Ценовые сегменты:</b>")
        ordered_labels = [label for label, _, _ in PRICE_BUCKETS] + ["Цена по запросу"]
        for label in ordered_labels:
            count = price_dist.get(label, 0)
            if count:
                lines.append(f"• {label}: {count}")

    if sold:
        lines.append("\n<b>Примеры проданного:</b>")
        for product in sold[:5]:
            lines.append(format_product_line(product, include_category=True))

    return "\n".join(lines)


def split_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    current = ""
    for line in text.split("\n"):
        chunk = f"{current}\n{line}".strip() if current else line
        if len(chunk) <= limit:
            current = chunk
            continue
        if current:
            parts.append(current)
        current = line
    if current:
        parts.append(current)
    return parts
