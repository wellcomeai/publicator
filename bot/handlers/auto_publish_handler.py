"""Хэндлер меню авто-публикации + расписание + настройки"""

import json
import re
import structlog
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from database.managers.user_manager import UserManager
from database.managers.agent_manager import AgentManager
from database.managers.channel_manager import ChannelManager
from database.managers.auto_publish_manager import AutoPublishManager
from database.managers.content_queue_manager import ContentQueueManager
from database.managers.post_manager import PostManager
from bot.states.states import AutoPublishSetup
from bot.keyboards.keyboards import (
    main_menu_kb,
    auto_publish_menu_kb,
    schedule_days_kb,
    auto_publish_settings_kb,
    review_post_kb,
)
from services.channel_service import publish_post
from utils.plan_utils import get_menu_flags, plan_allows_auto_publish, get_auto_publish_limits
from utils.html_sanitizer import sanitize_html
from config.settings import config

logger = structlog.get_logger()
router = Router()


# ============================================================
#  ГЛАВНОЕ МЕНЮ АВТО-ПУБЛИКАЦИИ
# ============================================================

@router.message(F.text == "📅 Авто-публикация")
async def auto_publish_menu(message: Message, state: FSMContext):
    """Точка входа: кнопка главного меню"""
    await state.clear()
    chat_id = message.from_user.id

    user = await UserManager.get_by_chat_id(chat_id)
    if not user:
        await message.answer("Сначала нажмите /start")
        return

    plan = user.get("plan", "free")
    if not plan_allows_auto_publish(plan):
        await message.answer(
            "⚠️ Авто-публикация доступна на тарифах Стартер и Про.\n\n"
            "Оформите подписку в разделе 💳 Подписка."
        )
        return

    await _show_auto_publish_menu(message, user)


async def _show_auto_publish_menu(message_or_cb, user: dict, edit: bool = False):
    """Показать главное меню авто-публикации"""
    user_id = user["id"]
    settings = await AutoPublishManager.get_settings(user_id)

    is_active = settings.get("is_active", False) if settings else False
    schedule = settings.get("schedule", {}) if settings else {}
    moderation = settings.get("moderation", "review") if settings else "review"
    generate_covers = settings.get("generate_covers", True) if settings else True
    has_schedule = bool(schedule.get("slots"))

    queue_count = await ContentQueueManager.get_active_queue_count(user_id)

    # Status text
    if is_active:
        status = "▶️ Активна"
    elif settings:
        status = "⏸ На паузе"
    else:
        status = "⚪ Не настроена"

    # Schedule text
    if has_schedule:
        slots = schedule.get("slots", [])
        day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        days_times = {}
        for s in sorted(slots, key=lambda x: (x["day"], x["time"])):
            day_name = day_names[s["day"]]
            if day_name not in days_times:
                days_times[day_name] = []
            days_times[day_name].append(s["time"])

        sched_lines = []
        for day, times in days_times.items():
            sched_lines.append(f"  {day} — {', '.join(times)}")
        schedule_text = "\n".join(sched_lines) + " (МСК)"
    else:
        schedule_text = "⚠️ Не настроено"

    # Next post
    next_text = ""
    if queue_count > 0:
        queue = await ContentQueueManager.get_queue(user_id, status="ready")
        if queue:
            first = queue[0]
            topic = first.get("topic", "")[:40]
            scheduled_at = first.get("scheduled_at")
            if scheduled_at:
                tz = ZoneInfo("Europe/Moscow")
                dt = scheduled_at.astimezone(tz) if scheduled_at.tzinfo else scheduled_at
                next_text = f"\n   Следующий: {dt.strftime('%a %H:%M')} — «{topic}»"

    mod_text = "👀 На проверку" if moderation == "review" else "📢 Автоматически"
    covers_text = "Да" if generate_covers else "Нет"

    text = (
        f"📅 <b>Авто-публикация</b>\n\n"
        f"Статус: {status}\n\n"
        f"⏰ Расписание:\n{schedule_text}\n\n"
        f"📋 В очереди: {queue_count} постов{next_text}\n\n"
        f"⚙️ Модерация: {mod_text}\n"
        f"🖼 Обложки: {covers_text}"
    )

    kb = auto_publish_menu_kb(is_active, has_schedule, queue_count)

    if edit and hasattr(message_or_cb, "message"):
        try:
            await message_or_cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await message_or_cb.message.answer(text, reply_markup=kb, parse_mode="HTML")
    elif hasattr(message_or_cb, "answer"):
        await message_or_cb.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await message_or_cb.message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "autopub:menu")
async def autopub_menu_callback(callback: CallbackQuery, state: FSMContext):
    """Возврат в меню авто-публикации"""
    await state.clear()
    chat_id = callback.from_user.id
    user = await UserManager.get_by_chat_id(chat_id)
    if not user:
        await callback.answer("Ошибка", show_alert=True)
        return
    await _show_auto_publish_menu(callback, user, edit=True)
    await callback.answer()


# ============================================================
#  НАСТРОЙКА РАСПИСАНИЯ
# ============================================================

@router.callback_query(F.data == "autopub:schedule")
async def schedule_setup(callback: CallbackQuery, state: FSMContext):
    """Начало настройки расписания"""
    chat_id = callback.from_user.id
    user = await UserManager.get_by_chat_id(chat_id)
    if not user:
        await callback.answer("Ошибка", show_alert=True)
        return

    # Load existing selected days
    settings = await AutoPublishManager.get_settings(user["id"])
    selected_days = []
    if settings and settings.get("schedule"):
        slots = settings["schedule"].get("slots", [])
        selected_days = list(set(s["day"] for s in slots))

    await state.set_state(AutoPublishSetup.choosing_days)
    await state.update_data(selected_days=selected_days)

    await callback.message.edit_text(
        "Выберите дни публикаций (нажмите для переключения):",
        reply_markup=schedule_days_kb(selected_days),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("autopub_day:"), AutoPublishSetup.choosing_days)
async def toggle_day(callback: CallbackQuery, state: FSMContext):
    """Toggle дня недели"""
    day = int(callback.data.split(":")[1])
    data = await state.get_data()
    selected_days = data.get("selected_days", [])

    if day in selected_days:
        selected_days.remove(day)
    else:
        selected_days.append(day)
        selected_days.sort()

    await state.update_data(selected_days=selected_days)

    try:
        await callback.message.edit_reply_markup(
            reply_markup=schedule_days_kb(selected_days)
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "autopub_days_done", AutoPublishSetup.choosing_days)
async def days_done(callback: CallbackQuery, state: FSMContext):
    """Дни выбраны, запрашиваем время"""
    data = await state.get_data()
    selected_days = data.get("selected_days", [])

    if not selected_days:
        await callback.answer("Выберите хотя бы один день!", show_alert=True)
        return

    # Check plan limits
    chat_id = callback.from_user.id
    user = await UserManager.get_by_chat_id(chat_id)
    plan = user.get("plan", "free") if user else "free"
    limits = get_auto_publish_limits(plan)

    await state.set_state(AutoPublishSetup.entering_times)

    max_note = ""
    max_slots = limits.get("max_slots_per_day")
    if max_slots and max_slots == 1:
        max_note = "\n\n⚠️ На тарифе Стартер — максимум 1 время."

    await callback.message.edit_text(
        f"В какое время публиковать? (МСК)\n\n"
        f"Введите время через запятую.\n"
        f"Примеры: 10:00  или  10:00, 18:00  или  09:00, 14:00, 20:00"
        f"{max_note}"
    )
    await callback.answer()


@router.message(AutoPublishSetup.entering_times)
async def process_times(message: Message, state: FSMContext, bot: Bot):
    """Обработка введённого времени"""
    text = message.text.strip()

    # Parse times
    time_pattern = re.compile(r"(\d{1,2}):(\d{2})")
    matches = time_pattern.findall(text)

    if not matches:
        await message.answer(
            "⚠️ Не удалось распознать время. Введите в формате ЧЧ:ММ.\n"
            "Примеры: 10:00  или  10:00, 18:00"
        )
        return

    times = []
    for h, m in matches:
        h, m = int(h), int(m)
        if 0 <= h <= 23 and 0 <= m <= 59:
            times.append(f"{h:02d}:{m:02d}")

    if not times:
        await message.answer("⚠️ Неверный формат времени.")
        return

    # Check plan limits
    chat_id = message.from_user.id
    user = await UserManager.get_by_chat_id(chat_id)
    plan = user.get("plan", "free") if user else "free"
    limits = get_auto_publish_limits(plan)

    max_slots = limits.get("max_slots_per_day")
    if max_slots and len(times) > max_slots:
        times = times[:max_slots]
        await message.answer(
            f"⚠️ На тарифе Стартер максимум {max_slots} время в день. Оставлено: {', '.join(times)}"
        )

    data = await state.get_data()
    selected_days = data.get("selected_days", [])

    # Build schedule
    slots = []
    for day in selected_days:
        for time_str in times:
            slots.append({"day": day, "time": time_str})

    schedule = {
        "mode": "weekly_slots",
        "timezone": "Europe/Moscow",
        "slots": slots,
    }

    # Save
    await AutoPublishManager.update_schedule(user["id"], schedule)

    # Recalculate scheduled_at for existing queue
    await ContentQueueManager.recalculate_scheduled_at(user["id"], schedule)

    await state.clear()

    # Format confirmation
    day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    lines = []
    for day in selected_days:
        lines.append(f"  {day_names[day]} — {', '.join(times)}")

    total_per_week = len(selected_days) * len(times)

    from bot.keyboards.keyboards import content_plan_menu_kb
    text = (
        f"✅ Расписание настроено!\n\n"
        f"📅 Публикации:\n"
        + "\n".join(lines) +
        f"\n  = {total_per_week} постов в неделю\n"
    )

    flags = await get_menu_flags(chat_id)
    await message.answer(text, reply_markup=main_menu_kb(**flags))


# ============================================================
#  НАСТРОЙКИ
# ============================================================

@router.callback_query(F.data == "autopub:settings")
async def settings_menu(callback: CallbackQuery, state: FSMContext):
    """Меню настроек авто-публикации"""
    chat_id = callback.from_user.id
    user = await UserManager.get_by_chat_id(chat_id)
    if not user:
        await callback.answer("Ошибка", show_alert=True)
        return

    settings = await AutoPublishManager.get_settings(user["id"])
    if not settings:
        settings = await AutoPublishManager.create_or_update_settings(user["id"])

    moderation = settings.get("moderation", "review")
    covers = settings.get("generate_covers", True)
    on_empty = settings.get("on_empty", "pause")

    mod_label = "На проверку" if moderation == "review" else "Автоматически"
    covers_label = "Да" if covers else "Нет"
    empty_label = "Пауза" if on_empty == "pause" else "Авто-генерация"

    text = (
        f"⚙️ <b>Настройки авто-публикации:</b>\n\n"
        f"👀 Модерация: {mod_label}\n"
        f"🖼 AI-обложки: {covers_label}\n"
        f"⏸ Если тем нет: {empty_label}\n\n"
        f"Нажмите для изменения:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=auto_publish_settings_kb(moderation, covers, on_empty),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("autopub_set:"))
async def toggle_setting(callback: CallbackQuery, state: FSMContext):
    """Toggle настроек"""
    field_map = {
        "moderation": "moderation",
        "covers": "generate_covers",
        "on_empty": "on_empty",
    }
    setting_key = callback.data.split(":")[1]
    field = field_map.get(setting_key)

    if not field:
        await callback.answer("Ошибка", show_alert=True)
        return

    chat_id = callback.from_user.id
    user = await UserManager.get_by_chat_id(chat_id)
    if not user:
        await callback.answer("Ошибка", show_alert=True)
        return

    plan = user.get("plan", "free")
    limits = get_auto_publish_limits(plan)

    # Check starter restrictions
    if field == "moderation" and limits.get("moderation_only_review"):
        await callback.answer(
            "На тарифе Стартер доступен только режим «На проверку». Обновите до Про.",
            show_alert=True,
        )
        return

    if field == "on_empty" and not limits.get("allow_ai_plan", True):
        # Starter can't use auto_generate since it needs AI plan
        settings = await AutoPublishManager.get_settings(user["id"])
        if settings and settings.get("on_empty") == "pause":
            await callback.answer(
                "Авто-генерация доступна на тарифе Про.",
                show_alert=True,
            )
            return

    new_val = await AutoPublishManager.toggle_setting(user["id"], field)

    # Refresh settings and update keyboard
    settings = await AutoPublishManager.get_settings(user["id"])
    moderation = settings.get("moderation", "review")
    covers = settings.get("generate_covers", True)
    on_empty = settings.get("on_empty", "pause")

    mod_label = "На проверку" if moderation == "review" else "Автоматически"
    covers_label = "Да" if covers else "Нет"
    empty_label = "Пауза" if on_empty == "pause" else "Авто-генерация"

    text = (
        f"⚙️ <b>Настройки авто-публикации:</b>\n\n"
        f"👀 Модерация: {mod_label}\n"
        f"🖼 AI-обложки: {covers_label}\n"
        f"⏸ Если тем нет: {empty_label}\n\n"
        f"Нажмите для изменения:"
    )

    try:
        await callback.message.edit_text(
            text,
            reply_markup=auto_publish_settings_kb(moderation, covers, on_empty),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()


# ============================================================
#  ВКЛЮЧЕНИЕ / ПАУЗА
# ============================================================

@router.callback_query(F.data == "autopub:toggle")
async def toggle_auto_publish(callback: CallbackQuery, state: FSMContext):
    """Включить/выключить авто-публикацию"""
    chat_id = callback.from_user.id
    user = await UserManager.get_by_chat_id(chat_id)
    if not user:
        await callback.answer("Ошибка", show_alert=True)
        return

    user_id = user["id"]
    settings = await AutoPublishManager.get_settings(user_id)

    if not settings:
        settings = await AutoPublishManager.create_or_update_settings(user_id)

    if settings.get("is_active"):
        # Pause
        await AutoPublishManager.set_active(user_id, False)
        await callback.answer("⏸ Авто-публикация приостановлена.")
        await _show_auto_publish_menu(callback, user, edit=True)
        return

    # Activate — run checks
    schedule = settings.get("schedule", {})
    if not schedule.get("slots"):
        await callback.answer("⚠️ Сначала настройте расписание", show_alert=True)
        return

    channel = await ChannelManager.get_channel(user_id)
    if not channel:
        await callback.answer("⚠️ Привяжите канал (📢 Мой канал)", show_alert=True)
        return

    agent = await AgentManager.get_agent(user_id)
    if not agent:
        await callback.answer("⚠️ Создайте агента (🤖 Мой агент)", show_alert=True)
        return

    ready_count = await ContentQueueManager.get_queue_count(user_id, status="ready")
    if ready_count == 0:
        await callback.answer("⚠️ Сгенерируйте контент-план", show_alert=True)
        return

    await AutoPublishManager.set_active(user_id, True)

    # Get next slot time
    next_slot = await AutoPublishManager.get_next_slot_time(user_id)
    if next_slot:
        tz = ZoneInfo("Europe/Moscow")
        next_msk = next_slot.astimezone(tz)
        await callback.answer(
            f"▶️ Включена! Следующий пост: {next_msk.strftime('%a %d.%m %H:%M')} МСК",
            show_alert=True,
        )
    else:
        await callback.answer("▶️ Авто-публикация включена!", show_alert=True)

    await _show_auto_publish_menu(callback, user, edit=True)


# ============================================================
#  ОБРАБОТКА КНОПОК REVIEW
# ============================================================

@router.callback_query(F.data.startswith("review_publish:"))
async def review_publish(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Опубликовать пост из review"""
    queue_id = int(callback.data.split(":")[1])
    chat_id = callback.from_user.id

    item = await ContentQueueManager.get_item(queue_id)
    if not item:
        await callback.answer("Пост не найден", show_alert=True)
        return

    user = await UserManager.get_by_chat_id(chat_id)
    if not user:
        await callback.answer("Ошибка", show_alert=True)
        return

    user_id = user["id"]
    post_id = item.get("post_id")

    if not post_id:
        await callback.answer("Пост не найден", show_alert=True)
        return

    post = await PostManager.get_post(post_id)
    if not post:
        await callback.answer("Пост не найден", show_alert=True)
        return

    channel = await ChannelManager.get_channel(user_id)
    if not channel:
        await callback.answer("⚠️ Канал не привязан", show_alert=True)
        return

    # Check post limit
    limit_info = await UserManager.check_post_limit(chat_id)
    if not limit_info.get("can_post"):
        await callback.answer("⚠️ Достигнут лимит постов за месяц", show_alert=True)
        return

    text = post.get("final_text") or post.get("generated_text") or ""
    media_info = post.get("media_info")
    if isinstance(media_info, str):
        media_info = json.loads(media_info)

    plan = user.get("plan", "free")
    watermark = (plan == "free")

    result = await publish_post(
        bot=bot,
        channel_id=channel["channel_id"],
        text=text,
        media_info=media_info,
        watermark=watermark,
    )

    if result["success"]:
        await ContentQueueManager.update_status(queue_id, "published")
        await PostManager.mark_published(post_id, channel["channel_id"])
        await UserManager.increment_post_count(chat_id)

        channel_ref = f"@{channel.get('channel_username', '')}" if channel.get("channel_username") else "канал"
        try:
            await callback.message.edit_text(
                f"✅ Пост опубликован в {channel_ref}!"
            )
        except Exception:
            pass
        await callback.answer("✅ Опубликовано!")
    else:
        error = result.get("error", "Unknown error")
        await callback.answer(f"❌ Ошибка: {error}", show_alert=True)


@router.callback_query(F.data.startswith("review_edit:"))
async def review_edit(callback: CallbackQuery, state: FSMContext):
    """Редактирование поста из review — переходим в карусель"""
    queue_id = int(callback.data.split(":")[1])
    item = await ContentQueueManager.get_item(queue_id)
    if not item:
        await callback.answer("Пост не найден", show_alert=True)
        return

    # Store that we came from review
    await state.update_data(from_review=True, review_queue_id=queue_id)

    # Import and show carousel for this item
    from bot.handlers.content_plan_handler import _show_carousel_item
    chat_id = callback.from_user.id
    user = await UserManager.get_by_chat_id(chat_id)
    if not user:
        await callback.answer("Ошибка", show_alert=True)
        return

    await _show_carousel_item(callback.message.chat.id, state, item["position"], user["id"], callback.bot)
    await callback.answer()


@router.callback_query(F.data.startswith("review_skip:"))
async def review_skip(callback: CallbackQuery, state: FSMContext):
    """Пропустить пост из review"""
    queue_id = int(callback.data.split(":")[1])
    await ContentQueueManager.update_status(queue_id, "skipped")

    try:
        await callback.message.edit_text("⏭ Пост пропущен.")
    except Exception:
        pass
    await callback.answer("Пост пропущен")


@router.callback_query(F.data.startswith("review_delete:"))
async def review_delete(callback: CallbackQuery, state: FSMContext):
    """Удалить пост из review"""
    queue_id = int(callback.data.split(":")[1])
    item = await ContentQueueManager.get_item(queue_id)
    if item:
        user_id = item["user_id"]
        await ContentQueueManager.delete_item(queue_id)

        # Recalculate
        settings = await AutoPublishManager.get_settings(user_id)
        if settings and settings.get("schedule"):
            await ContentQueueManager.recalculate_scheduled_at(user_id, settings["schedule"])

    try:
        await callback.message.edit_text("🗑 Пост удалён из очереди.")
    except Exception:
        pass
    await callback.answer("Удалено")
