"""Хэндлер расписания публикаций"""

import structlog
from datetime import datetime, timezone, timedelta
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from database.managers.user_manager import UserManager
from database.managers.post_manager import PostManager
from database.managers.channel_manager import ChannelManager
from database.managers.schedule_manager import ScheduleManager
from bot.states.states import SchedulePost
from bot.keyboards.keyboards import (
    schedule_time_presets_kb, scheduled_list_kb, main_menu_kb, cancel_kb
)
from config.settings import config

logger = structlog.get_logger()
router = Router()


# ===== БЫСТРЫЕ ПРЕСЕТЫ ВРЕМЕНИ =====

@router.callback_query(F.data.startswith("schedule:"))
async def schedule_post_start(callback: CallbackQuery, state: FSMContext):
    """Начало планирования — показать быстрые варианты"""
    await callback.answer()
    post_id = int(callback.data.split(":")[1])

    # Проверка плана
    user = await UserManager.get_by_chat_id(callback.from_user.id)
    plan = user.get("plan", "free") if user else "free"
    plan_config = config.PLANS.get(plan, config.PLANS["free"])

    if not plan_config.get("allow_schedule"):
        await callback.message.answer(
            "⚠️ Расписание доступно на тарифе <b>Про</b>.\n"
            "Перейдите в раздел 💳 Подписка для апгрейда.",
            parse_mode="HTML"
        )
        return

    # Проверяем что канал привязан
    channel = await ChannelManager.get_channel(user["id"])
    if not channel:
        await callback.message.answer(
            "⚠️ Сначала привяжите канал (📢 Мой канал)."
        )
        return

    await state.update_data(schedule_post_id=post_id)

    await callback.message.answer(
        "📅 <b>Когда опубликовать?</b>\n\n"
        "Выберите время или введите вручную:\n"
        "<i>Формат: ДД.ММ.ГГГГ ЧЧ:ММ (московское время)</i>\n"
        "<i>Например: 15.01.2026 10:00</i>",
        parse_mode="HTML",
        reply_markup=schedule_time_presets_kb(post_id)
    )
    await state.set_state(SchedulePost.waiting_datetime)


# ===== БЫСТРЫЕ ВАРИАНТЫ =====

@router.callback_query(SchedulePost.waiting_datetime, F.data.startswith("sched_quick:"))
async def schedule_quick(callback: CallbackQuery, state: FSMContext):
    """Быстрое планирование: через 1ч, 3ч, завтра 10:00"""
    await callback.answer()

    parts = callback.data.split(":")
    quick_type = parts[1]
    post_id = int(parts[2])

    now = datetime.now(timezone.utc)

    if quick_type == "1h":
        publish_at = now + timedelta(hours=1)
        time_display = "через 1 час"
    elif quick_type == "3h":
        publish_at = now + timedelta(hours=3)
        time_display = "через 3 часа"
    elif quick_type == "tomorrow_10":
        # Завтра 10:00 МСК = 07:00 UTC
        tomorrow = now + timedelta(days=1)
        publish_at = tomorrow.replace(hour=7, minute=0, second=0, microsecond=0)
        time_display = "завтра в 10:00 МСК"
    elif quick_type == "tomorrow_18":
        tomorrow = now + timedelta(days=1)
        publish_at = tomorrow.replace(hour=15, minute=0, second=0, microsecond=0)
        time_display = "завтра в 18:00 МСК"
    else:
        await callback.message.answer("❌ Неизвестный вариант.")
        return

    await _confirm_schedule(callback.message, state, post_id, publish_at, time_display,
                            callback.from_user.id)


# ===== РУЧНОЙ ВВОД ДАТЫ =====

@router.message(SchedulePost.waiting_datetime, F.text)
async def schedule_manual_datetime(message: Message, state: FSMContext):
    """Парсинг даты из текстового ввода: ДД.ММ.ГГГГ ЧЧ:ММ (МСК)"""
    data = await state.get_data()
    post_id = data.get("schedule_post_id")
    if not post_id:
        await message.answer("❌ Ошибка. Начните заново.")
        await state.clear()
        return

    text = message.text.strip()
    msk_offset = timezone(timedelta(hours=3))

    formats = [
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y %H.%M",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d %H:%M",
    ]

    parsed = None
    for fmt in formats:
        try:
            parsed = datetime.strptime(text, fmt)
            break
        except ValueError:
            continue

    if not parsed:
        await message.answer(
            "❌ Не удалось разобрать дату.\n"
            "Используйте формат: <b>ДД.ММ.ГГГГ ЧЧ:ММ</b>\n"
            "<i>Например: 15.01.2026 10:00</i>",
            parse_mode="HTML"
        )
        return

    # Считаем введённое время как МСК → конвертируем в UTC
    publish_at_msk = parsed.replace(tzinfo=msk_offset)
    publish_at_utc = publish_at_msk.astimezone(timezone.utc)

    now = datetime.now(timezone.utc)
    if publish_at_utc <= now:
        await message.answer("❌ Время должно быть в будущем. Попробуйте ещё раз:")
        return

    time_display = parsed.strftime("%d.%m.%Y в %H:%M МСК")
    await _confirm_schedule(message, state, post_id, publish_at_utc, time_display,
                            message.from_user.id)


# ===== ПОДТВЕРЖДЕНИЕ =====

async def _confirm_schedule(message, state, post_id, publish_at, time_display, chat_id):
    """Сохранение в БД и подтверждение"""
    user = await UserManager.get_by_chat_id(chat_id)
    if not user:
        return

    channel = await ChannelManager.get_channel(user["id"])
    if not channel:
        await message.answer("⚠️ Канал не привязан.")
        return

    # Проверяем лимит постов
    limit_info = await UserManager.check_post_limit(chat_id)
    if not limit_info["can_post"]:
        await message.answer(
            f"⚠️ Достигнут лимит постов ({limit_info['posts_limit']}/мес).\n"
            f"Перейдите на более высокий тариф."
        )
        return

    await ScheduleManager.schedule_post(
        post_id=post_id,
        user_id=user["id"],
        channel_id=channel["channel_id"],
        publish_at=publish_at,
    )

    await PostManager.update_post_status(post_id, "scheduled")

    await state.clear()

    ch_display = f"@{channel['channel_username']}" if channel.get("channel_username") else channel.get("channel_title", "канал")

    await message.answer(
        f"✅ Пост запланирован!\n\n"
        f"📅 {time_display}\n"
        f"📢 Канал: {ch_display}\n\n"
        f"Управлять расписанием: 📅 Расписание",
        reply_markup=main_menu_kb(show_schedule=True),
        parse_mode="HTML"
    )


# ===== СПИСОК ЗАПЛАНИРОВАННЫХ =====

@router.message(F.text == "📅 Расписание")
async def show_schedule(message: Message, state: FSMContext):
    """Показать запланированные посты"""
    await state.clear()
    user = await UserManager.get_by_chat_id(message.from_user.id)
    if not user:
        await message.answer("Сначала нажмите /start")
        return

    scheduled = await ScheduleManager.get_user_scheduled(user["id"])

    if not scheduled:
        await message.answer(
            "📅 Нет запланированных публикаций.\n\n"
            "Создайте пост и нажмите «📅 Запланировать»."
        )
        return

    msk_offset = timedelta(hours=3)
    text = "📅 <b>Запланированные публикации:</b>\n\n"

    for i, item in enumerate(scheduled[:10], 1):
        publish_at = item["publish_at"]
        if publish_at.tzinfo:
            msk_time = publish_at + msk_offset
        else:
            msk_time = publish_at
        time_str = msk_time.strftime("%d.%m %H:%M МСК")

        post_text = item.get("final_text") or item.get("generated_text") or ""
        preview = post_text[:60] + "..." if len(post_text) > 60 else post_text

        text += f"{i}. 📅 {time_str}\n<i>{preview}</i>\n\n"

    await message.answer(text, parse_mode="HTML", reply_markup=scheduled_list_kb(scheduled))


# ===== ОТМЕНА ЗАПЛАНИРОВАННОГО =====

@router.callback_query(F.data.startswith("sched_cancel:"))
async def cancel_scheduled_post(callback: CallbackQuery):
    await callback.answer()
    schedule_id = int(callback.data.split(":")[1])
    success = await ScheduleManager.cancel_scheduled(schedule_id)

    if success:
        await callback.message.answer("✅ Публикация отменена.")
    else:
        await callback.message.answer("❌ Не удалось отменить (возможно, уже опубликовано).")
