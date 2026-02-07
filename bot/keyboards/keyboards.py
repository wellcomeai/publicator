"""Клавиатуры бота"""

from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)


# ===== ГЛАВНОЕ МЕНЮ =====

def main_menu_kb(show_schedule: bool = False, show_watcher: bool = False) -> ReplyKeyboardMarkup:
    """Главное меню. show_schedule для Про, show_watcher для Стартер/Про."""
    keyboard = [
        [KeyboardButton(text="✍️ Создать пост"), KeyboardButton(text="🔄 Рерайт поста")],
        [KeyboardButton(text="🤖 Мой агент"), KeyboardButton(text="📢 Мой канал")],
    ]

    row3 = []
    if show_schedule:
        row3.append(KeyboardButton(text="📅 Расписание"))
    if show_watcher:
        row3.append(KeyboardButton(text="📡 Источники"))
    row3.append(KeyboardButton(text="👤 Профиль"))
    keyboard.append(row3)

    keyboard.append([KeyboardButton(text="💳 Подписка")])

    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


# ===== ДЕЙСТВИЯ С ПОСТОМ =====

def post_actions_kb(post_id: int, can_schedule: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура действий с постом. can_schedule=True для тарифа Про."""
    buttons = [
        [InlineKeyboardButton(text="📢 Опубликовать", callback_data=f"publish:{post_id}")],
    ]

    if can_schedule:
        buttons.append([
            InlineKeyboardButton(text="📅 Запланировать", callback_data=f"schedule:{post_id}")
        ])

    buttons.append([
        InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit:{post_id}"),
        InlineKeyboardButton(text="🖼 Медиа", callback_data=f"media:{post_id}"),
    ])
    buttons.append([
        InlineKeyboardButton(text="🔄 Заново", callback_data=f"regenerate:{post_id}"),
    ])
    buttons.append([
        InlineKeyboardButton(text="🗑 Отменить", callback_data=f"discard:{post_id}"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


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
        [InlineKeyboardButton(text="⭐ Стартер — 100₽/мес", callback_data="pay:plan:starter")],
        [InlineKeyboardButton(text="🚀 Про — 300₽/мес", callback_data="pay:plan:pro")],
        [InlineKeyboardButton(text="━━━ Пакеты токенов ━━━", callback_data="noop")],
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


# ===== ОНБОРДИНГ =====

def preset_choice_kb() -> InlineKeyboardMarkup:
    """Клавиатура выбора пресета агента"""
    from config.presets import AGENT_PRESETS
    buttons = []
    for key, preset in AGENT_PRESETS.items():
        buttons.append([InlineKeyboardButton(
            text=f"{preset['emoji']} {preset['name']}",
            callback_data=f"preset:{key}"
        )])
    buttons.append([InlineKeyboardButton(text="✏️ Свой вариант", callback_data="preset:custom")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def onboarding_channel_kb() -> InlineKeyboardMarkup:
    """Кнопка пропуска привязки канала"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Пропустить", callback_data="onboard:skip_channel")]
    ])


def onboarding_first_post_kb() -> InlineKeyboardMarkup:
    """Кнопки после завершения онбординга"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Создать первый пост", callback_data="onboard:first_post")],
        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="onboard:to_menu")],
    ])


# ===== РАСПИСАНИЕ =====

def schedule_time_presets_kb(post_id: int) -> InlineKeyboardMarkup:
    """Быстрые варианты времени"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⏰ Через 1 час", callback_data=f"sched_quick:1h:{post_id}"),
            InlineKeyboardButton(text="⏰ Через 3 часа", callback_data=f"sched_quick:3h:{post_id}"),
        ],
        [
            InlineKeyboardButton(text="🌅 Завтра 10:00", callback_data=f"sched_quick:tomorrow_10:{post_id}"),
            InlineKeyboardButton(text="🌆 Завтра 18:00", callback_data=f"sched_quick:tomorrow_18:{post_id}"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
    ])


def scheduled_list_kb(scheduled_items: list) -> InlineKeyboardMarkup:
    """Кнопки отмены запланированных постов"""
    buttons = []
    for item in scheduled_items[:5]:
        buttons.append([InlineKeyboardButton(
            text=f"❌ Отменить #{item['id']}",
            callback_data=f"sched_cancel:{item['id']}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ===== ИСТОЧНИКИ (WATCHER) =====

def watcher_menu_kb(channels: list, can_add: bool = True) -> InlineKeyboardMarkup:
    """Меню управления каналами-источниками"""
    buttons = []

    if can_add:
        buttons.append([InlineKeyboardButton(text="➕ Добавить канал", callback_data="watcher:add")])

    for ch in channels:
        buttons.append([InlineKeyboardButton(
            text=f"❌ Удалить @{ch['channel_username']}",
            callback_data=f"watcher:remove:{ch['id']}"
        )])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def watcher_post_kb(watched_channel_id: int, post_id: int) -> InlineKeyboardMarkup:
    """Кнопки под уведомлением о новом посте"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🔄 Рерайт",
                callback_data=f"watcher_rewrite:{watched_channel_id}:{post_id}"
            ),
            InlineKeyboardButton(
                text="⏭ Пропустить",
                callback_data=f"watcher_skip:{watched_channel_id}:{post_id}"
            ),
        ]
    ])


# ===== ОТМЕНА =====

def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])
