from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeDefault

BOT_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Перезапустить бота"),
    BotCommand(command="status", description="Статус сканирования"),
    BotCommand(command="scan", description="Сканировать каталог"),
    BotCommand(command="sold", description="Ушло с сайта"),
    BotCommand(command="new", description="Новые поступления"),
    BotCommand(command="top", description="Топ брендов"),
    BotCommand(command="fast", description="Ходовые бренды"),
    BotCommand(command="price", description="Ценовые сегменты"),
    BotCommand(command="stats", description="Статистика по бренду"),
    BotCommand(command="report", description="Полная сводка"),
    BotCommand(command="help", description="Список команд"),
]


async def setup_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands(BOT_COMMANDS, scope=BotCommandScopeDefault())
