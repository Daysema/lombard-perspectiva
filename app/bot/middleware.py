from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.config import settings

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


class AuthMiddleware(BaseMiddleware):
    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user_id = None
        if isinstance(event, Message) and event.from_user is not None:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user is not None:
            user_id = event.from_user.id

        if user_id is None:
            return await handler(event, data)

        if user_id not in settings.allowed_user_ids:
            if isinstance(event, Message):
                await event.answer("⛔ Доступ запрещён. Бот доступен только администраторам.")
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔ Доступ запрещён.", show_alert=True)
            return None

        return await handler(event, data)
