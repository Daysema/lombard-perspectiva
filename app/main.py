import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.bot.commands import setup_bot_commands
from app.bot.handlers import router
from app.bot.middleware import AuthMiddleware
from app.config import settings
from app.db.session import init_db
from app.scheduler.jobs import run_scan, setup_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    if not settings.allowed_user_ids:
        raise RuntimeError("TELEGRAM_ALLOWED_USER_IDS must contain at least one admin user id")

    await init_db()
    logger.info("Database initialized")

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    dispatcher.message.middleware(AuthMiddleware())
    dispatcher.include_router(router)

    await setup_bot_commands(bot)
    logger.info("Bot commands menu configured")

    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("Scheduler started")

    asyncio.create_task(run_scan())

    logger.info("Bot started for admins: %s", settings.allowed_user_ids)
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
