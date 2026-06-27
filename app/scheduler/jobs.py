import logging
from zoneinfo import ZoneInfo

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.reports.builder import build_summary_report, split_message
from app.reports.service import Period, report_service
from app.scraper.scanner import CatalogScanner

logger = logging.getLogger(__name__)


async def run_scan(bot: Bot) -> None:
    logger.info("Scheduled scan started")
    scanner = CatalogScanner()
    try:
        scan = await scanner.run()
        logger.info(
            "Scan finished: found=%s new=%s removed=%s",
            scan.products_found,
            scan.new_count,
            scan.removed_count,
        )
    except Exception:
        logger.exception("Scheduled scan failed")


async def send_report(bot: Bot, days: int, title: str) -> None:
    period = Period(days)
    async with async_session() as session:
        data = await report_service.summary(session, period)

    text = f"<b>{title}</b>\n\n{build_summary_report(data)}"
    for user_id in settings.allowed_user_ids:
        for part in split_message(text):
            try:
                await bot.send_message(user_id, part)
            except Exception:
                logger.exception("Failed to send report to user %s", user_id)


async def send_daily_report(bot: Bot) -> None:
    await send_report(bot, days=1, title="📅 Ежедневный отчёт")


async def send_weekly_report(bot: Bot) -> None:
    await send_report(bot, days=7, title="📅 Еженедельный отчёт")


async def send_monthly_report(bot: Bot) -> None:
    await send_report(bot, days=30, title="📅 Ежемесячный отчёт")


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    tz = ZoneInfo(settings.timezone)
    scheduler = AsyncIOScheduler(timezone=tz)

    scheduler.add_job(
        run_scan,
        CronTrigger(hour="0,12", minute=0, timezone=tz),
        args=[bot],
        id="catalog_scan",
        replace_existing=True,
    )

    scheduler.add_job(
        send_daily_report,
        CronTrigger(hour=settings.report_daily_hour, minute=0, timezone=tz),
        args=[bot],
        id="daily_report",
        replace_existing=True,
    )

    scheduler.add_job(
        send_weekly_report,
        CronTrigger(
            day_of_week=settings.report_weekly_day,
            hour=settings.report_daily_hour,
            minute=0,
            timezone=tz,
        ),
        args=[bot],
        id="weekly_report",
        replace_existing=True,
    )

    scheduler.add_job(
        send_monthly_report,
        CronTrigger(
            day=settings.report_monthly_day,
            hour=settings.report_daily_hour,
            minute=0,
            timezone=tz,
        ),
        args=[bot],
        id="monthly_report",
        replace_existing=True,
    )

    return scheduler
