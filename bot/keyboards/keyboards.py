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
            InlineKeyboardButton(text="📢 Опубликовать", callback_data=f"publish:{post_id}"),
        ],
        [
            InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit:{post_id}"),
            InlineKeyboardButton(text="🖼 Медиа", callback_data=f"media:{post_id}"),
        ],
        [
            InlineKeyboardButton(text="🔄 Похожий", callback_data=f"clone:{post_id}"),
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


# ===== МЕДИА =====

def media_actions_kb(post_id: int, items_count: int) -> InlineKeyboardMarkup:
    """Клавиатура управления медиа"""
    buttons = []

    if items_count < 10:
        buttons.append([
            InlineKeyboardButton(text="🎨 Картинка (AI)", callback_data=f"media_gen_image:{post_id}"),
            InlineKeyboardButton(text="🎬 Видео (AI)", callback_data=f"media_gen_video:{post_id}"),
        ])
        buttons.append([
            InlineKeyboardButton(text="📎 Загрузить своё", callback_data=f"media_upload:{post_id}"),
        ])

    if items_count > 0:
        buttons.append([
            InlineKeyboardButton(text="🗑 Удалить медиа", callback_data=f"media_delete:{post_id}"),
        ])

    buttons.append([
        InlineKeyboardButton(text="✅ Готово", callback_data=f"media_done:{post_id}"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def image_prompt_kb(post_id: int) -> InlineKeyboardMarkup:
    """Выбор промта для генерации картинки"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 По теме поста", callback_data=f"media_gen_image_auto:{post_id}")],
        [InlineKeyboardButton(text="✏️ Свой промт", callback_data=f"media_gen_image_custom:{post_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"media:{post_id}")],
    ])


def video_prompt_kb(post_id: int) -> InlineKeyboardMarkup:
    """Выбор промта для генерации видео"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 По теме поста", callback_data=f"media_gen_video_auto:{post_id}")],
        [InlineKeyboardButton(text="✏️ Свой промт", callback_data=f"media_gen_video_custom:{post_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"media:{post_id}")],
    ])


def video_duration_kb(post_id: int, prompt_type: str) -> InlineKeyboardMarkup:
    """Выбор длительности видео"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="4 сек (~$0.40)", callback_data=f"media_video_dur:4:{post_id}:{prompt_type}"),
            InlineKeyboardButton(text="8 сек (~$0.80)", callback_data=f"media_video_dur:8:{post_id}:{prompt_type}"),
        ],
        [
            InlineKeyboardButton(text="12 сек (~$1.20)", callback_data=f"media_video_dur:12:{post_id}:{prompt_type}"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"media:{post_id}")],
    ])


def media_upload_done_kb(post_id: int) -> InlineKeyboardMarkup:
    """Кнопка завершения загрузки медиа"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Готово", callback_data=f"media_upload_done:{post_id}")],
    ])


# ===== ПРОФИЛЬ / НАСТРОЙКИ =====

def profile_settings_kb(auto_cover: bool) -> InlineKeyboardMarkup:
    """Кнопки настроек в профиле"""
    cover_text = "🖼 Авто-обложка: ВКЛ" if auto_cover else "🖼 Авто-обложка: ВЫКЛ"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=cover_text, callback_data="toggle_auto_cover")],
    ])


# ===== ОТМЕНА =====

def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])
