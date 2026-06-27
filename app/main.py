import asyncio
import logging
import traceback

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import ErrorEvent
from apscheduler.events import EVENT_JOB_ERROR

from app.bot.commands import setup_bot_commands
from app.bot.handlers import router
from app.bot.middleware import AuthMiddleware
from app.config import settings
from app.db.session import init_db
from app.notifications.alerts import format_exception, send_error_alert, send_fatal_startup_alert
from app.notifications.logging_handler import TelegramAlertHandler
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

    logging.getLogger("app").addHandler(TelegramAlertHandler(bot))

    dispatcher = Dispatcher()

    @dispatcher.errors()
    async def on_dispatcher_error(event: ErrorEvent) -> None:
        exc = event.exception
        if exc is None:
            return
        await send_error_alert(
            bot,
            "Ошибка обработки Telegram",
            format_exception(exc),
        )

    dispatcher.message.middleware(AuthMiddleware())
    dispatcher.callback_query.middleware(AuthMiddleware())
    dispatcher.include_router(router)

    await setup_bot_commands(bot)
    logger.info("Bot commands menu configured")

    scheduler = setup_scheduler(bot)
    scheduler.add_listener(
        lambda event: asyncio.create_task(
            send_error_alert(
                bot,
                f"Ошибка планировщика: {event.job_id}",
                format_exception(event.exception) if event.exception else "Unknown error",
            )
        ),
        EVENT_JOB_ERROR,
    )
    scheduler.start()
    logger.info("Scheduler started")

    loop = asyncio.get_running_loop()

    def on_asyncio_exception(_loop: asyncio.AbstractEventLoop, context: dict) -> None:
        message = context.get("message", "Asyncio exception")
        exc = context.get("exception")
        body = f"{message}\n\n{format_exception(exc)}" if exc else message
        asyncio.create_task(send_error_alert(bot, "Ошибка asyncio", body))

    loop.set_exception_handler(on_asyncio_exception)

    asyncio.create_task(run_scan(bot))

    logger.info("Bot started for admins: %s", settings.allowed_user_ids)
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        logging.exception("Fatal error")
        asyncio.run(send_fatal_startup_alert(format_exception(exc)))
        raise
