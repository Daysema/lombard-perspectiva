import hashlib
import logging
import time
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import BufferedInputFile

from app.config import settings

logger = logging.getLogger(__name__)

_COOLDOWN_SECONDS = 300
_last_sent_at: dict[str, float] = {}


async def send_error_alert(bot: Bot, title: str, body: str) -> None:
    if not settings.allowed_user_ids:
        return

    digest = hashlib.sha256(f"{title}\n{body[:500]}".encode()).hexdigest()[:16]
    now = time.time()
    if now - _last_sent_at.get(digest, 0) < _COOLDOWN_SECONDS:
        return
    _last_sent_at[digest] = now

    timestamp = datetime.now(ZoneInfo(settings.timezone)).strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"error_{timestamp}.txt"
    content = f"{title}\n{'=' * 60}\n\n{body.strip()}\n"
    document = BufferedInputFile(content.encode("utf-8"), filename=filename)
    caption = f"🚨 {title}"

    for user_id in settings.allowed_user_ids:
        try:
            await bot.send_document(chat_id=user_id, document=document, caption=caption)
        except Exception:
            logger.exception("Failed to send error alert to %s", user_id)


async def send_fatal_startup_alert(message: str) -> None:
    try:
        bot = Bot(token=settings.telegram_bot_token)
        await send_error_alert(bot, "Критическая ошибка запуска", message)
        await bot.session.close()
    except Exception:
        logger.exception("Failed to send fatal startup alert")


def format_exception(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
