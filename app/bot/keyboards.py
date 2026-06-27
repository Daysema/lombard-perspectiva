from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.pagination import (
    PG_BRAND_STATS,
    PG_BRAND_TOP,
    PG_DELISTED,
    PG_NEW,
    PG_NOOP,
    PG_SOLD,
    pg_brand_stats,
    pg_brand_top,
    pg_delisted,
    pg_new,
    pg_sold,
)

MENU_MAIN = "menu:main"
MENU_STATUS = "menu:status"
MENU_SOLD = "menu:sold"
MENU_DELISTED = "menu:delisted"
MENU_NEW = "menu:new"
MENU_TOP = "menu:top"
MENU_FAST = "menu:fast"
MENU_PRICE = "menu:price"
MENU_STATS = "menu:stats"
MENU_REPORT = "menu:report"

DEFAULT_DAYS = 7


def parse_top_days(callback_data: str) -> int:
    parts = callback_data.split(":")
    if len(parts) >= 3 and parts[2].isdigit():
        return int(parts[2])
    return DEFAULT_DAYS


def top_brand_callback(days: int, index: int) -> str:
    return f"top_brand:{days}:{index}"


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data=MENU_MAIN)]]
    )


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📡 Статус", callback_data=MENU_STATUS),
                InlineKeyboardButton(text="✅ Продано", callback_data=MENU_SOLD),
            ],
            [
                InlineKeyboardButton(text="📤 Снято", callback_data=MENU_DELISTED),
                InlineKeyboardButton(text="🆕 Новые", callback_data=MENU_NEW),
            ],
            [
                InlineKeyboardButton(text="🏆 Топ брендов", callback_data=MENU_TOP),
                InlineKeyboardButton(text="🔥 Ходовые", callback_data=MENU_FAST),
            ],
            [
                InlineKeyboardButton(text="💰 Цены", callback_data=MENU_PRICE),
                InlineKeyboardButton(text="📈 Сводка", callback_data=MENU_REPORT),
            ],
            [InlineKeyboardButton(text="📊 Статистика бренда", callback_data=MENU_STATS)],
        ]
    )


def top_brands_keyboard(brands: list[tuple[str, int]], days: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, (brand, count) in enumerate(brands):
        label = f"{brand} — {count} шт."
        if len(label) > 60:
            label = label[:57] + "..."
        rows.append(
            [InlineKeyboardButton(text=label, callback_data=top_brand_callback(days, index))]
        )
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data=MENU_MAIN)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_to_top_keyboard(days: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ К топу брендов", callback_data=f"{MENU_TOP}:{days}")],
            [InlineKeyboardButton(text="◀️ В меню", callback_data=MENU_MAIN)],
        ]
    )


def _pagination_row(
    page: int,
    total_pages: int,
    prev_data: str | None,
    next_data: str | None,
) -> list[InlineKeyboardButton]:
    row: list[InlineKeyboardButton] = []
    if page > 0 and prev_data:
        row.append(InlineKeyboardButton(text="◀️ Назад", callback_data=prev_data))
    row.append(InlineKeyboardButton(text=f"{page + 1} / {total_pages}", callback_data=PG_NOOP))
    if page < total_pages - 1 and next_data:
        row.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=next_data))
    return row


def list_pagination_keyboard(
    section: str,
    days: int,
    page: int,
    total_pages: int,
    *,
    brand_index: int | None = None,
    brand_name: str | None = None,
) -> InlineKeyboardMarkup:
    if section == PG_SOLD:
        prev_data = pg_sold(days, page - 1) if page > 0 else None
        next_data = pg_sold(days, page + 1) if page < total_pages - 1 else None
    elif section == PG_DELISTED:
        prev_data = pg_delisted(days, page - 1) if page > 0 else None
        next_data = pg_delisted(days, page + 1) if page < total_pages - 1 else None
    elif section == PG_NEW:
        prev_data = pg_new(days, page - 1) if page > 0 else None
        next_data = pg_new(days, page + 1) if page < total_pages - 1 else None
    elif section == PG_BRAND_TOP and brand_index is not None:
        prev_data = pg_brand_top(days, brand_index, page - 1) if page > 0 else None
        next_data = pg_brand_top(days, brand_index, page + 1) if page < total_pages - 1 else None
    elif section == PG_BRAND_STATS and brand_name:
        prev_data = pg_brand_stats(days, page - 1, brand_name) if page > 0 else None
        next_data = pg_brand_stats(days, page + 1, brand_name) if page < total_pages - 1 else None
    else:
        prev_data = next_data = None

    rows: list[list[InlineKeyboardButton]] = []
    if total_pages > 1:
        rows.append(_pagination_row(page, total_pages, prev_data, next_data))

    if section == PG_BRAND_TOP and brand_index is not None:
        rows.append(
            [InlineKeyboardButton(text="◀️ К топу брендов", callback_data=f"{MENU_TOP}:{days}")]
        )
        rows.append([InlineKeyboardButton(text="◀️ В меню", callback_data=MENU_MAIN)])
    else:
        rows.append([InlineKeyboardButton(text="◀️ В меню", callback_data=MENU_MAIN)])

    return InlineKeyboardMarkup(inline_keyboard=rows)
