import html
from datetime import datetime

from app.db.models import Product, ScanRun
from app.reports.service import PRICE_BUCKETS, Period

TELEGRAM_MESSAGE_LIMIT = 4000


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
        "Команды:\n"
        "/status — статус последнего сканирования\n"
        "/scan — запустить сканирование вручную\n"
        "/sold [дней] — продано (подтверждено архивом)\n"
        "/delisted [дней] — снято с витрины (не в архиве)\n"
        "/new [дней] — новые поступления\n"
        "/top [дней] — топ брендов по продажам\n"
        "/fast [дней] — самые ходовые бренды (быстрее уходят)\n"
        "/price [дней] — ценовые сегменты проданного\n"
        "/stats Бренд [дней] — статистика по бренду\n"
        "/report [дней] — полная сводка\n\n"
        "По умолчанию период — 7 дней. Автоотчёты: ежедневно, еженедельно, ежемесячно."
    )


def build_status_text(scan: ScanRun | None, active_count: int) -> str:
    if scan is None:
        return "Сканирование ещё не выполнялось."

    if scan.finished_at:
        finished = scan.finished_at.strftime("%d.%m.%Y %H:%M")
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


def build_sold_report(products: list[Product], period: Period) -> str:
    header = f"✅ <b>Продано {period.label}</b> (в архиве на сайте): {len(products)} шт.\n"
    if not products:
        return header + "\nНет данных за выбранный период."

    lines = [header]
    for product in products[:30]:
        removed = product.removed_at.strftime("%d.%m") if product.removed_at else "?"
        lines.append(f"{format_product_line(product, include_category=True)} — {removed}")

    if len(products) > 30:
        lines.append(f"\n… и ещё {len(products) - 30} позиций")
    return "\n".join(lines)


def build_delisted_report(products: list[Product], period: Period) -> str:
    header = f"📤 <b>Снято с витрины {period.label}</b> (нет в архиве): {len(products)} шт.\n"
    if not products:
        return header + "\nНет данных за выбранный период."

    lines = [header]
    for product in products[:30]:
        removed = product.removed_at.strftime("%d.%m") if product.removed_at else "?"
        lines.append(f"{format_product_line(product, include_category=True)} — {removed}")

    if len(products) > 30:
        lines.append(f"\n… и ещё {len(products) - 30} позиций")
    return "\n".join(lines)


def build_new_report(products: list[Product], period: Period) -> str:
    header = f"🆕 <b>Новые поступления {period.label}</b>: {len(products)} шт.\n"
    if not products:
        return header + "\nНет новых товаров за выбранный период."

    lines = [header]
    for product in products[:30]:
        appeared = product.first_seen_at.strftime("%d.%m") if product.first_seen_at else "?"
        lines.append(f"{format_product_line(product, include_category=True)} — {appeared}")

    if len(products) > 30:
        lines.append(f"\n… и ещё {len(products) - 30} позиций")
    return "\n".join(lines)


def build_top_brands_report(brands: list[tuple[str, int]], period: Period) -> str:
    lines = [f"🏆 <b>Топ брендов по продажам {period.label}</b>"]
    if not brands:
        lines.append("\nНет данных.")
        return "\n".join(lines)

    for index, (brand, count) in enumerate(brands, start=1):
        lines.append(f"{index}. {_esc(brand)} — {count} шт.")
    return "\n".join(lines)


def build_fast_brands_report(brands: list[tuple[str, float, int]], period: Period) -> str:
    lines = [f"🔥 <b>Ходовые бренды {period.label}</b> (среднее время на сайте)"]
    if not brands:
        lines.append("\nНет данных.")
        return "\n".join(lines)

    for index, (brand, avg_days, count) in enumerate(brands, start=1):
        lines.append(f"{index}. {_esc(brand)} — {avg_days:.1f} дн. ({count} шт.)")
    return "\n".join(lines)


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


def build_brand_stats_report(stats: dict, period: Period) -> str:
    brand = _esc(stats["brand"])
    lines = [
        f"📊 <b>Статистика: {brand}</b> ({period.label})",
        f"Продано: {stats['sold_count']} шт.",
        f"Сейчас в каталоге: {stats['active_count']} шт.",
    ]
    if stats["avg_price"] is not None:
        lines.append(f"Средняя цена проданного: {format_money(stats['avg_price'])}")

    sold: list[Product] = stats["sold"]
    if sold:
        lines.append("\nПоследние продажи:")
        for product in sold[:10]:
            lines.append(format_product_line(product))
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
