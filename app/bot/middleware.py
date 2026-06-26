from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from app.config import settings

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


class AuthMiddleware(BaseMiddleware):
    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        if not isinstance(event, Message) or event.from_user is None:
            return await handler(event, data)

        if event.from_user.id not in settings.allowed_user_ids:
            await event.answer("⛔ Доступ запрещён. Бот доступен только авторизованным пользователям.")
            return None

        return await handler(event, data)
