import asyncio
import logging
import traceback

from aiogram import Bot

from app.notifications.alerts import send_error_alert


class TelegramAlertHandler(logging.Handler):
    """Отправляет ERROR из модулей app.* админам в Telegram файлом."""

    def __init__(self, bot: Bot) -> None:
        super().__init__(level=logging.ERROR)
        self.bot = bot
        self.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )

    def emit(self, record: logging.LogRecord) -> None:
        if not record.name.startswith("app"):
            return

        try:
            message = self.format(record)
            if record.exc_info:
                message += "\n\n" + "".join(traceback.format_exception(*record.exc_info))

            loop = asyncio.get_running_loop()
            loop.create_task(
                send_error_alert(self.bot, f"Ошибка: {record.name}", message),
                name=f"telegram-alert-{record.name}",
            )
        except Exception:
            self.handleError(record)
