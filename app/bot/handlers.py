import re

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.bot.keyboards import (
    DEFAULT_DAYS,
    MENU_DELISTED,
    MENU_FAST,
    MENU_MAIN,
    MENU_NEW,
    MENU_PRICE,
    MENU_REPORT,
    MENU_SOLD,
    MENU_STATS,
    MENU_STATUS,
    MENU_TOP,
    back_keyboard,
    list_pagination_keyboard,
    main_menu_keyboard,
    parse_top_days,
    top_brands_keyboard,
)
from app.bot.pagination import (
    PG_BRAND_STATS,
    PG_BRAND_TOP,
    PG_DELISTED,
    PG_NEW,
    PG_SOLD,
    parse_pg_callback,
    resolve_brand_token,
)
from app.db.session import async_session
from app.reports.builder import (
    build_brand_stats_report,
    build_delisted_report,
    build_fast_brands_report,
    build_help_text,
    build_new_report,
    build_price_report,
    build_sold_report,
    build_status_text,
    build_summary_report,
    build_top_brands_report,
    split_message,
)
from app.reports.service import Period, report_service

router = Router()


def parse_days(command: CommandObject | None, default: int = DEFAULT_DAYS) -> int:
    if command is None or not command.args:
        return default
    match = re.search(r"\d+", command.args)
    if not match:
        return default
    return max(1, min(int(match.group()), 365))


def parse_brand_and_days(command: CommandObject | None) -> tuple[str | None, int]:
    if command is None or not command.args:
        return None, DEFAULT_DAYS

    parts = command.args.strip().split()
    days = DEFAULT_DAYS
    brand_parts: list[str] = []

    for part in parts:
        if part.isdigit():
            days = max(1, min(int(part), 365))
        else:
            brand_parts.append(part)

    brand = " ".join(brand_parts).strip() or None
    return brand, days


async def show_page(
    message: Message,
    text: str,
    keyboard: InlineKeyboardMarkup | None,
    *,
    edit: bool = False,
) -> None:
    try:
        if edit:
            await message.edit_text(text, reply_markup=keyboard)
        else:
            await message.answer(text, reply_markup=keyboard)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            return
        if edit:
            await message.answer(text, reply_markup=keyboard)
        else:
            raise


async def show_loading(callback: CallbackQuery) -> None:
    if callback.message:
        try:
            await callback.message.edit_text("⏳ Загрузка...")
        except TelegramBadRequest:
            pass


async def fetch_status_text() -> str:
    async with async_session() as session:
        scan = await report_service.get_last_scan(session)
        active_count = await report_service.active_count(session)
    return build_status_text(scan, active_count)


async def fetch_sold_view(days: int, page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    period = Period(days)
    async with async_session() as session:
        products = await report_service.sold_products(session, period)
    text, page, total_pages = build_sold_report(products, period, page)
    keyboard = list_pagination_keyboard(PG_SOLD, days, page, total_pages)
    return text, keyboard


async def fetch_delisted_view(days: int, page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    period = Period(days)
    async with async_session() as session:
        products = await report_service.delisted_products(session, period)
    text, page, total_pages = build_delisted_report(products, period, page)
    keyboard = list_pagination_keyboard(PG_DELISTED, days, page, total_pages)
    return text, keyboard


async def fetch_new_view(days: int, page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    period = Period(days)
    async with async_session() as session:
        products = await report_service.new_products(session, period)
    text, page, total_pages = build_new_report(products, period, page)
    keyboard = list_pagination_keyboard(PG_NEW, days, page, total_pages)
    return text, keyboard


async def fetch_top_view(days: int) -> tuple[str, InlineKeyboardMarkup]:
    period = Period(days)
    async with async_session() as session:
        brands = await report_service.top_brands(session, period)
    text = build_top_brands_report(brands, period)
    keyboard = top_brands_keyboard(brands, days) if brands else back_keyboard()
    return text, keyboard


async def fetch_brand_detail_view(
    days: int, brand_index: int, page: int = 0
) -> tuple[str, InlineKeyboardMarkup] | None:
    period = Period(days)
    async with async_session() as session:
        brands = await report_service.top_brands(session, period)
        if brand_index >= len(brands):
            return None
        brand_name, _ = brands[brand_index]
        stats = await report_service.brand_stats(session, brand_name, period, exact=True)

    text, page, total_pages = build_brand_stats_report(stats, period, page)
    keyboard = list_pagination_keyboard(
        PG_BRAND_TOP, days, page, total_pages, brand_index=brand_index
    )
    return text, keyboard


async def fetch_brand_stats_view(
    brand: str, days: int, page: int = 0, *, exact: bool = False
) -> tuple[str, InlineKeyboardMarkup] | None:
    period = Period(days)
    async with async_session() as session:
        stats = await report_service.brand_stats(session, brand, period, exact=exact)

    if stats["sold_count"] == 0 and stats["active_count"] == 0:
        return None

    text, page, total_pages = build_brand_stats_report(stats, period, page)
    keyboard = list_pagination_keyboard(
        PG_BRAND_STATS, days, page, total_pages, brand_name=stats["brand"]
    )
    return text, keyboard


async def fetch_fast_text(days: int) -> str:
    period = Period(days)
    async with async_session() as session:
        brands = await report_service.fastest_selling_brands(session, period)
    return build_fast_brands_report(brands, period)


async def fetch_price_text(days: int) -> str:
    period = Period(days)
    async with async_session() as session:
        distribution = await report_service.price_distribution(session, period)
    return build_price_report(distribution, period)


async def fetch_report_parts(days: int) -> list[str]:
    period = Period(days)
    async with async_session() as session:
        data = await report_service.summary(session, period)
    return split_message(build_summary_report(data))


@router.message(Command("start", "help"))
async def cmd_start(message: Message) -> None:
    await message.answer(build_help_text(), reply_markup=main_menu_keyboard())


@router.callback_query(F.data == MENU_MAIN)
async def cb_menu_main(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(build_help_text(), reply_markup=main_menu_keyboard())


@router.callback_query(F.data == MENU_STATUS)
async def cb_menu_status(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        text = await fetch_status_text()
        await callback.message.edit_text(text, reply_markup=back_keyboard())


@router.callback_query(F.data == MENU_SOLD)
async def cb_menu_sold(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        text, keyboard = await fetch_sold_view(DEFAULT_DAYS)
        await show_page(callback.message, text, keyboard, edit=True)


@router.callback_query(F.data == MENU_DELISTED)
async def cb_menu_delisted(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        text, keyboard = await fetch_delisted_view(DEFAULT_DAYS)
        await show_page(callback.message, text, keyboard, edit=True)


@router.callback_query(F.data == MENU_NEW)
async def cb_menu_new(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        text, keyboard = await fetch_new_view(DEFAULT_DAYS)
        await show_page(callback.message, text, keyboard, edit=True)


@router.callback_query((F.data == MENU_TOP) | F.data.startswith(f"{MENU_TOP}:"))
async def cb_menu_top(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message and callback.data:
        await show_loading(callback)
        days = parse_top_days(callback.data)
        text, keyboard = await fetch_top_view(days)
        await show_page(callback.message, text, keyboard, edit=True)


@router.callback_query(F.data.startswith("top_brand:"))
async def cb_top_brand(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message or not callback.data:
        return

    parts = callback.data.split(":")
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        return

    await show_loading(callback)
    days = int(parts[1])
    brand_index = int(parts[2])
    result = await fetch_brand_detail_view(days, brand_index)
    if result is None:
        await callback.answer("Бренд не найден", show_alert=True)
        return

    text, keyboard = result
    await show_page(callback.message, text, keyboard, edit=True)


@router.callback_query(F.data.startswith("pg:"))
async def cb_pagination(callback: CallbackQuery) -> None:
    parsed = parse_pg_callback(callback.data or "")
    if parsed is None:
        return

    if parsed["type"] == "noop":
        await callback.answer()
        return

    if not callback.message:
        return

    await callback.answer()

    if parsed["type"] == PG_SOLD:
        text, keyboard = await fetch_sold_view(parsed["days"], parsed["page"])
    elif parsed["type"] == PG_DELISTED:
        text, keyboard = await fetch_delisted_view(parsed["days"], parsed["page"])
    elif parsed["type"] == PG_NEW:
        text, keyboard = await fetch_new_view(parsed["days"], parsed["page"])
    elif parsed["type"] == PG_BRAND_TOP:
        result = await fetch_brand_detail_view(
            parsed["days"], parsed["brand_index"], parsed["page"]
        )
        if result is None:
            await callback.answer("Бренд не найден", show_alert=True)
            return
        text, keyboard = result
    elif parsed["type"] == PG_BRAND_STATS:
        async with async_session() as session:
            candidates = await report_service.distinct_brands(session)
        brand = resolve_brand_token(parsed["brand_token"], candidates)
        if brand is None:
            await callback.answer("Бренд не найден", show_alert=True)
            return
        result = await fetch_brand_stats_view(brand, parsed["days"], parsed["page"], exact=True)
        if result is None:
            await callback.answer("Бренд не найден", show_alert=True)
            return
        text, keyboard = result
    else:
        return

    await show_page(callback.message, text, keyboard, edit=True)


@router.callback_query(F.data == MENU_FAST)
async def cb_menu_fast(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        text = await fetch_fast_text(DEFAULT_DAYS)
        await callback.message.edit_text(text, reply_markup=back_keyboard())


@router.callback_query(F.data == MENU_PRICE)
async def cb_menu_price(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        text = await fetch_price_text(DEFAULT_DAYS)
        await callback.message.edit_text(text, reply_markup=back_keyboard())


@router.callback_query(F.data == MENU_REPORT)
async def cb_menu_report(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        parts = await fetch_report_parts(DEFAULT_DAYS)
        await callback.message.edit_text(parts[0], reply_markup=back_keyboard())
        for part in parts[1:]:
            await callback.message.answer(part)


@router.callback_query(F.data == MENU_STATS)
async def cb_menu_stats(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        text = (
            "📊 <b>Статистика по бренду</b>\n\n"
            "Отправьте команду с названием бренда:\n"
            "<code>/stats Rolex</code>\n"
            "<code>/stats Rolex 30</code> — за 30 дней"
        )
        await callback.message.edit_text(text, reply_markup=back_keyboard())


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    text = await fetch_status_text()
    await message.answer(text, reply_markup=back_keyboard())


@router.message(Command("sold"))
async def cmd_sold(message: Message, command: CommandObject) -> None:
    text, keyboard = await fetch_sold_view(parse_days(command))
    await show_page(message, text, keyboard, edit=False)


@router.message(Command("delisted"))
async def cmd_delisted(message: Message, command: CommandObject) -> None:
    text, keyboard = await fetch_delisted_view(parse_days(command))
    await show_page(message, text, keyboard, edit=False)


@router.message(Command("new"))
async def cmd_new(message: Message, command: CommandObject) -> None:
    text, keyboard = await fetch_new_view(parse_days(command))
    await show_page(message, text, keyboard, edit=False)


@router.message(Command("top"))
async def cmd_top(message: Message, command: CommandObject) -> None:
    days = parse_days(command)
    text, keyboard = await fetch_top_view(days)
    await message.answer(text, reply_markup=keyboard)


@router.message(Command("fast"))
async def cmd_fast(message: Message, command: CommandObject) -> None:
    text = await fetch_fast_text(parse_days(command))
    await message.answer(text, reply_markup=back_keyboard())


@router.message(Command("price"))
async def cmd_price(message: Message, command: CommandObject) -> None:
    text = await fetch_price_text(parse_days(command))
    await message.answer(text, reply_markup=back_keyboard())


@router.message(Command("stats"))
async def cmd_stats(message: Message, command: CommandObject) -> None:
    brand, days = parse_brand_and_days(command)
    if not brand:
        await message.answer(
            "Укажите бренд: /stats Rolex 30",
            reply_markup=back_keyboard(),
        )
        return

    result = await fetch_brand_stats_view(brand, days, exact=False)
    if result is None:
        await message.answer(
            f"Бренд «{brand}» не найден в данных.",
            reply_markup=back_keyboard(),
        )
        return

    text, keyboard = result
    await show_page(message, text, keyboard, edit=False)


@router.message(Command("report"))
async def cmd_report(message: Message, command: CommandObject) -> None:
    parts = await fetch_report_parts(parse_days(command))
    await message.answer(parts[0], reply_markup=back_keyboard())
    for part in parts[1:]:
        await message.answer(part)


@router.message(F.text)
async def unknown_message(message: Message) -> None:
    await message.answer(
        "Неизвестная команда. Откройте меню: /start",
        reply_markup=main_menu_keyboard(),
    )
