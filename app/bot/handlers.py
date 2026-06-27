import re

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
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
    main_menu_keyboard,
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


async def send_parts(
    message: Message,
    parts: list[str],
    keyboard: InlineKeyboardMarkup,
    *,
    edit: bool = False,
) -> None:
    if not parts:
        return
    if edit:
        await message.edit_text(parts[0], reply_markup=keyboard)
        for part in parts[1:]:
            await message.answer(part)
    else:
        await message.answer(parts[0], reply_markup=keyboard)
        for part in parts[1:]:
            await message.answer(part)


async def fetch_status_text() -> str:
    async with async_session() as session:
        scan = await report_service.get_last_scan(session)
        active_count = await report_service.active_count(session)
    return build_status_text(scan, active_count)


async def fetch_sold_parts(days: int) -> list[str]:
    period = Period(days)
    async with async_session() as session:
        products = await report_service.sold_products(session, period)
    return split_message(build_sold_report(products, period))


async def fetch_delisted_parts(days: int) -> list[str]:
    period = Period(days)
    async with async_session() as session:
        products = await report_service.delisted_products(session, period)
    return split_message(build_delisted_report(products, period))


async def fetch_new_parts(days: int) -> list[str]:
    period = Period(days)
    async with async_session() as session:
        products = await report_service.new_products(session, period)
    return split_message(build_new_report(products, period))


async def fetch_top_text(days: int) -> str:
    period = Period(days)
    async with async_session() as session:
        brands = await report_service.top_brands(session, period)
    return build_top_brands_report(brands, period)


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
        parts = await fetch_sold_parts(DEFAULT_DAYS)
        await send_parts(callback.message, parts, back_keyboard(), edit=True)


@router.callback_query(F.data == MENU_DELISTED)
async def cb_menu_delisted(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        parts = await fetch_delisted_parts(DEFAULT_DAYS)
        await send_parts(callback.message, parts, back_keyboard(), edit=True)


@router.callback_query(F.data == MENU_NEW)
async def cb_menu_new(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        parts = await fetch_new_parts(DEFAULT_DAYS)
        await send_parts(callback.message, parts, back_keyboard(), edit=True)


@router.callback_query(F.data == MENU_TOP)
async def cb_menu_top(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        text = await fetch_top_text(DEFAULT_DAYS)
        await callback.message.edit_text(text, reply_markup=back_keyboard())


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
        await send_parts(callback.message, parts, back_keyboard(), edit=True)


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
    parts = await fetch_sold_parts(parse_days(command))
    await send_parts(message, parts, back_keyboard())


@router.message(Command("delisted"))
async def cmd_delisted(message: Message, command: CommandObject) -> None:
    parts = await fetch_delisted_parts(parse_days(command))
    await send_parts(message, parts, back_keyboard())


@router.message(Command("new"))
async def cmd_new(message: Message, command: CommandObject) -> None:
    parts = await fetch_new_parts(parse_days(command))
    await send_parts(message, parts, back_keyboard())


@router.message(Command("top"))
async def cmd_top(message: Message, command: CommandObject) -> None:
    text = await fetch_top_text(parse_days(command))
    await message.answer(text, reply_markup=back_keyboard())


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

    period = Period(days)
    async with async_session() as session:
        stats = await report_service.brand_stats(session, brand, period)

    if stats["sold_count"] == 0 and stats["active_count"] == 0:
        await message.answer(
            f"Бренд «{brand}» не найден в данных.",
            reply_markup=back_keyboard(),
        )
        return

    parts = split_message(build_brand_stats_report(stats, period))
    await send_parts(message, parts, back_keyboard())


@router.message(Command("report"))
async def cmd_report(message: Message, command: CommandObject) -> None:
    parts = await fetch_report_parts(parse_days(command))
    await send_parts(message, parts, back_keyboard())


@router.message(F.text)
async def unknown_message(message: Message) -> None:
    await message.answer(
        "Неизвестная команда. Откройте меню: /start",
        reply_markup=main_menu_keyboard(),
    )
