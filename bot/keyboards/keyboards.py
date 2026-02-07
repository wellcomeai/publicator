"""Клавиатуры бота"""

from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)


# ===== ГЛАВНОЕ МЕНЮ =====

def main_menu_kb(show_schedule: bool = False, show_auto_publish: bool = False) -> ReplyKeyboardMarkup:
    """Главное меню. show_schedule для Про, show_auto_publish для starter+."""
    keyboard = [
        [KeyboardButton(text="✍️ Создать пост"), KeyboardButton(text="🔄 Рерайт поста")],
        [KeyboardButton(text="🤖 Мой агент"), KeyboardButton(text="📢 Мой канал")],
    ]

    row3 = []
    if show_auto_publish:
        row3.append(KeyboardButton(text="📅 Авто-публикация"))
    elif show_schedule:
        row3.append(KeyboardButton(text="📅 Расписание"))
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


# ===== ОТМЕНА =====

def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])


# ===== АВТО-ПУБЛИКАЦИЯ =====

def auto_publish_menu_kb(is_active: bool, has_schedule: bool, queue_count: int) -> InlineKeyboardMarkup:
    """Главное меню авто-публикации"""
    buttons = [
        [InlineKeyboardButton(text="⏰ Расписание", callback_data="autopub:schedule")],
        [InlineKeyboardButton(text="📋 Контент-план", callback_data="autopub:plan")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="autopub:settings")],
    ]
    if is_active:
        buttons.append([InlineKeyboardButton(text="⏸ Пауза", callback_data="autopub:toggle")])
    else:
        buttons.append([InlineKeyboardButton(text="▶️ Включить", callback_data="autopub:toggle")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def schedule_days_kb(selected_days: list) -> InlineKeyboardMarkup:
    """Выбор дней недели с toggle"""
    day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    row1 = []
    row2 = []
    for i, name in enumerate(day_names):
        check = "✅" if i in selected_days else "⬜"
        btn = InlineKeyboardButton(text=f"{check} {name}", callback_data=f"autopub_day:{i}")
        if i < 4:
            row1.append(btn)
        else:
            row2.append(btn)
    buttons = [row1, row2]
    buttons.append([
        InlineKeyboardButton(text="✅ Далее", callback_data="autopub_days_done"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="autopub:menu"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def schedule_times_kb(selected_times: list) -> InlineKeyboardMarkup:
    """Выбор времени публикаций кнопками (08:00-23:00)"""
    buttons = []
    hours = list(range(8, 24))
    row = []
    for h in hours:
        time_str = f"{h:02d}:00"
        check = "✅" if time_str in selected_times else ""
        label = f"{check} {time_str}" if check else time_str
        row.append(InlineKeyboardButton(
            text=label,
            callback_data=f"autopub_time:{time_str}"
        ))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([
        InlineKeyboardButton(text="🌙 00:00–07:00", callback_data="autopub_time_night")
    ])
    buttons.append([
        InlineKeyboardButton(text="✅ Готово", callback_data="autopub_times_done"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="autopub:menu"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def schedule_times_night_kb(selected_times: list) -> InlineKeyboardMarkup:
    """Ночные часы 00:00-07:00"""
    buttons = []
    hours = list(range(0, 8))
    row = []
    for h in hours:
        time_str = f"{h:02d}:00"
        check = "✅" if time_str in selected_times else ""
        label = f"{check} {time_str}" if check else time_str
        row.append(InlineKeyboardButton(
            text=label,
            callback_data=f"autopub_time:{time_str}"
        ))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([
        InlineKeyboardButton(text="☀️ 08:00–23:00", callback_data="autopub_time_day")
    ])
    buttons.append([
        InlineKeyboardButton(text="✅ Готово", callback_data="autopub_times_done"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="autopub:menu"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def auto_publish_settings_kb(moderation: str, covers: bool, on_empty: str) -> InlineKeyboardMarkup:
    """Настройки авто-публикации с toggle кнопками"""
    mod_text = "👀 Модерация: На проверку" if moderation == "review" else "📢 Модерация: Автоматически"
    covers_text = "🖼 Обложки: ВКЛ" if covers else "🖼 Обложки: ВЫКЛ"
    empty_text = "⏸ Если пусто: Пауза" if on_empty == "pause" else "🤖 Если пусто: Авто-генерация"

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=mod_text, callback_data="autopub_set:moderation")],
        [InlineKeyboardButton(text=covers_text, callback_data="autopub_set:covers")],
        [InlineKeyboardButton(text=empty_text, callback_data="autopub_set:on_empty")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="autopub:menu")],
    ])


def content_plan_menu_kb() -> InlineKeyboardMarkup:
    """Меню контент-плана"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Сгенерировать план", callback_data="cplan:generate")],
        [InlineKeyboardButton(text="📝 Добавить тему", callback_data="cplan:add_topic")],
        [InlineKeyboardButton(text="📄 Просмотр очереди", callback_data="cplan:browse")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="autopub:menu")],
    ])


def generate_plan_covers_kb() -> InlineKeyboardMarkup:
    """Спрос обложек перед генерацией"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, с обложками", callback_data="cplan_gen:with_covers")],
        [InlineKeyboardButton(text="❌ Только текст", callback_data="cplan_gen:no_covers")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="autopub:plan")],
    ])


def carousel_kb(queue_id: int, position: int, total: int) -> InlineKeyboardMarkup:
    """Кнопки карусели под превью поста"""
    nav_row = []
    if position > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"cplan_nav:prev:{position}"))
    nav_row.append(InlineKeyboardButton(text=f"{position}/{total}", callback_data="noop"))
    if position < total:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"cplan_nav:next:{position}"))

    return InlineKeyboardMarkup(inline_keyboard=[
        nav_row,
        [
            InlineKeyboardButton(text="✏️ Текст", callback_data=f"cplan_edit:{queue_id}"),
            InlineKeyboardButton(text="🖼 Обложка", callback_data=f"cplan_cover:{queue_id}"),
        ],
        [
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"cplan_delete:{queue_id}"),
            InlineKeyboardButton(text="➕ Вставить", callback_data=f"cplan_insert:{queue_id}"),
        ],
    ])


def carousel_edit_text_kb(queue_id: int) -> InlineKeyboardMarkup:
    """Варианты редактирования текста"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Свои правки", callback_data=f"cplan_textedit:custom:{queue_id}")],
        [InlineKeyboardButton(text="🔄 Перегенерировать", callback_data=f"cplan_textedit:regen:{queue_id}")],
        [InlineKeyboardButton(text="📋 Сменить тему", callback_data=f"cplan_textedit:newtopic:{queue_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"cplan_nav:stay:{queue_id}")],
    ])


def carousel_cover_kb(queue_id: int, has_cover: bool) -> InlineKeyboardMarkup:
    """Управление обложкой"""
    buttons = [
        [InlineKeyboardButton(text="🔄 Сгенерировать (авто)", callback_data=f"cplan_cover_auto:{queue_id}")],
        [InlineKeyboardButton(text="✏️ Свой промт", callback_data=f"cplan_cover_prompt:{queue_id}")],
        [InlineKeyboardButton(text="📎 Загрузить фото", callback_data=f"cplan_cover_upload:{queue_id}")],
    ]
    if has_cover:
        buttons.append([InlineKeyboardButton(text="🗑 Убрать обложку", callback_data=f"cplan_cover_remove:{queue_id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"cplan_nav:stay:{queue_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def plan_ready_notification_kb() -> InlineKeyboardMarkup:
    """Уведомление о готовности контент-плана"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Смотреть посты", callback_data="cplan:browse")],
        [InlineKeyboardButton(text="▶️ Включить авто-публикацию", callback_data="autopub:toggle")],
    ])


def review_post_kb(queue_id: int) -> InlineKeyboardMarkup:
    """Кнопки модерации поста"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Опубликовать", callback_data=f"review_publish:{queue_id}")],
        [
            InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"review_edit:{queue_id}"),
            InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"review_skip:{queue_id}"),
        ],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"review_delete:{queue_id}")],
    ])


def topic_added_kb() -> InlineKeyboardMarkup:
    """Кнопки после добавления темы"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Ещё тему", callback_data="cplan:add_topic")],
        [InlineKeyboardButton(text="📄 Смотреть очередь", callback_data="cplan:browse")],
        [InlineKeyboardButton(text="✅ Готово", callback_data="autopub:menu")],
    ])


def confirm_delete_queue_kb(queue_id: int) -> InlineKeyboardMarkup:
    """Подтверждение удаления поста из очереди"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да", callback_data=f"cplan_confirm_del:{queue_id}"),
            InlineKeyboardButton(text="❌ Нет", callback_data=f"cplan_nav:stay:{queue_id}"),
        ],
    ])
