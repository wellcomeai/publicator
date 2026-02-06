"""Клавиатуры бота"""

from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)


# ===== ГЛАВНОЕ МЕНЮ =====

def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✍️ Создать пост"), KeyboardButton(text="🔄 Рерайт поста")],
            [KeyboardButton(text="🤖 Мой агент"), KeyboardButton(text="📢 Мой канал")],
            [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="💳 Подписка")],
        ],
        resize_keyboard=True,
    )


# ===== ДЕЙСТВИЯ С ПОСТОМ =====

def post_actions_kb(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"publish:{post_id}"),
        ],
        [
            InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit:{post_id}"),
            InlineKeyboardButton(text="🔄 Заново", callback_data=f"regenerate:{post_id}"),
        ],
        [
            InlineKeyboardButton(text="🗑 Отменить", callback_data=f"discard:{post_id}"),
        ],
    ])


# ===== АГЕНТ =====

def agent_menu_kb(has_agent: bool) -> InlineKeyboardMarkup:
    buttons = []
    if has_agent:
        buttons.append([InlineKeyboardButton(text="📋 Информация", callback_data="agent:info")])
        buttons.append([InlineKeyboardButton(text="✏️ Изменить промт", callback_data="agent:edit")])
        buttons.append([InlineKeyboardButton(text="🗑 Удалить агента", callback_data="agent:delete")])
    else:
        buttons.append([InlineKeyboardButton(text="➕ Создать агента", callback_data="agent:create")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def agent_confirm_delete_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, удалить", callback_data="agent:confirm_delete"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="agent:cancel_delete"),
        ]
    ])


# ===== КАНАЛ =====

def channel_menu_kb(has_channel: bool) -> InlineKeyboardMarkup:
    buttons = []
    if has_channel:
        buttons.append([InlineKeyboardButton(text="📋 Информация", callback_data="channel:info")])
        buttons.append([InlineKeyboardButton(text="🔗 Привязать другой", callback_data="channel:link")])
        buttons.append([InlineKeyboardButton(text="❌ Отвязать", callback_data="channel:unlink")])
    else:
        buttons.append([InlineKeyboardButton(text="🔗 Привязать канал", callback_data="channel:link")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ===== ПОДПИСКА =====

def subscription_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Подписка — 300₽/мес", callback_data="pay:subscription")],
        [InlineKeyboardButton(text="🪙 50K токенов — 100₽", callback_data="pay:tokens:50000")],
        [InlineKeyboardButton(text="🪙 150K токенов — 250₽", callback_data="pay:tokens:150000")],
        [InlineKeyboardButton(text="🪙 500K токенов — 700₽", callback_data="pay:tokens:500000")],
    ])


# ===== ОТМЕНА =====

def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])
