from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

MENU_MAIN = "menu:main"
MENU_STATUS = "menu:status"
MENU_SOLD = "menu:sold"
MENU_DELISTED = "menu:delisted"
MENU_NEW = "menu:new"
MENU_TOP = "menu:top"
MENU_FAST = "menu:fast"
MENU_PRICE = "menu:price"
MENU_STATS = "menu:stats"
MENU_REPORT = "menu:report"

DEFAULT_DAYS = 7


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data=MENU_MAIN)]]
    )


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📡 Статус", callback_data=MENU_STATUS),
                InlineKeyboardButton(text="✅ Продано", callback_data=MENU_SOLD),
            ],
            [
                InlineKeyboardButton(text="📤 Снято", callback_data=MENU_DELISTED),
                InlineKeyboardButton(text="🆕 Новые", callback_data=MENU_NEW),
            ],
            [
                InlineKeyboardButton(text="🏆 Топ брендов", callback_data=MENU_TOP),
                InlineKeyboardButton(text="🔥 Ходовые", callback_data=MENU_FAST),
            ],
            [
                InlineKeyboardButton(text="💰 Цены", callback_data=MENU_PRICE),
                InlineKeyboardButton(text="📈 Сводка", callback_data=MENU_REPORT),
            ],
            [InlineKeyboardButton(text="📊 Статистика бренда", callback_data=MENU_STATS)],
        ]
    )
