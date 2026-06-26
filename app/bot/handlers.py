import logging
import re

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.db.session import async_session
from app.reports.builder import (
    build_brand_stats_report,
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
from app.scraper.scanner import CatalogScanner

logger = logging.getLogger(__name__)
router = Router()


def parse_days(command: CommandObject | None, default: int = 7) -> int:
    if command is None or not command.args:
        return default
    match = re.search(r"\d+", command.args)
    if not match:
        return default
    return max(1, min(int(match.group()), 365))


def parse_brand_and_days(command: CommandObject | None) -> tuple[str | None, int]:
    if command is None or not command.args:
        return None, 7

    parts = command.args.strip().split()
    days = 7
    brand_parts: list[str] = []

    for part in parts:
        if part.isdigit():
            days = max(1, min(int(part), 365))
        else:
            brand_parts.append(part)

    brand = " ".join(brand_parts).strip() or None
    return brand, days


@router.message(Command("start", "help"))
async def cmd_start(message: Message) -> None:
    await message.answer(build_help_text())


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    async with async_session() as session:
        scan = await report_service.get_last_scan(session)
        active_count = await report_service.active_count(session)
    await message.answer(build_status_text(scan, active_count))


@router.message(Command("scan"))
async def cmd_scan(message: Message) -> None:
    await message.answer("⏳ Запускаю сканирование всех категорий…")
    scanner = CatalogScanner()
    try:
        async with async_session() as session:
            scan = await scanner.run(session)
    except RuntimeError as exc:
        await message.answer(f"⏳ {exc}")
        return
    except Exception:
        logger.exception("Manual scan failed")
        await message.answer("❌ Ошибка при сканировании. Проверьте логи контейнера.")
        return

    text = (
        "✅ Сканирование завершено.\n"
        f"Найдено: {scan.products_found}\n"
        f"Новых: {scan.new_count}\n"
        f"Ушло с сайта: {scan.removed_count}\n"
        f"Изменений цены: {scan.price_changed_count}"
    )
    await message.answer(text)


@router.message(Command("sold"))
async def cmd_sold(message: Message, command: CommandObject) -> None:
    period = Period(parse_days(command))
    async with async_session() as session:
        products = await report_service.sold_products(session, period)
    for part in split_message(build_sold_report(products, period)):
        await message.answer(part)


@router.message(Command("new"))
async def cmd_new(message: Message, command: CommandObject) -> None:
    period = Period(parse_days(command))
    async with async_session() as session:
        products = await report_service.new_products(session, period)
    for part in split_message(build_new_report(products, period)):
        await message.answer(part)


@router.message(Command("top"))
async def cmd_top(message: Message, command: CommandObject) -> None:
    period = Period(parse_days(command))
    async with async_session() as session:
        brands = await report_service.top_brands(session, period)
    await message.answer(build_top_brands_report(brands, period))


@router.message(Command("fast"))
async def cmd_fast(message: Message, command: CommandObject) -> None:
    period = Period(parse_days(command))
    async with async_session() as session:
        brands = await report_service.fastest_selling_brands(session, period)
    await message.answer(build_fast_brands_report(brands, period))


@router.message(Command("price"))
async def cmd_price(message: Message, command: CommandObject) -> None:
    period = Period(parse_days(command))
    async with async_session() as session:
        distribution = await report_service.price_distribution(session, period)
    await message.answer(build_price_report(distribution, period))


@router.message(Command("stats"))
async def cmd_stats(message: Message, command: CommandObject) -> None:
    brand, days = parse_brand_and_days(command)
    if not brand:
        await message.answer("Укажите бренд: /stats Rolex 30")
        return

    period = Period(days)
    async with async_session() as session:
        stats = await report_service.brand_stats(session, brand, period)

    if stats["sold_count"] == 0 and stats["active_count"] == 0:
        await message.answer(f"Бренд «{brand}» не найден в данных.")
        return

    for part in split_message(build_brand_stats_report(stats, period)):
        await message.answer(part)


@router.message(Command("report"))
async def cmd_report(message: Message, command: CommandObject) -> None:
    period = Period(parse_days(command))
    async with async_session() as session:
        data = await report_service.summary(session, period)
    for part in split_message(build_summary_report(data)):
        await message.answer(part)


@router.message(F.text)
async def unknown_message(message: Message) -> None:
    await message.answer("Неизвестная команда. Напишите /help")
