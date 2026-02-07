"""Хэндлер контент-плана: генерация, ручное добавление, карусель"""

import json
import structlog
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InputMediaPhoto, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from database.managers.user_manager import UserManager
from database.managers.agent_manager import AgentManager
from database.managers.channel_manager import ChannelManager
from database.managers.auto_publish_manager import AutoPublishManager
from database.managers.content_queue_manager import ContentQueueManager
from database.managers.post_manager import PostManager
from database.managers.plan_chat_manager import PlanChatManager
from services.media_manager import PostMediaManager
from services import openai_service
from services import image_service
from services.content_plan_service import generate_content_plan, generate_post_for_topic, generate_cover_for_post
from services.plan_chat_service import PlanChatService
from services.whisper_service import transcribe_voice
from bot.states.states import ContentPlan
from bot.keyboards.keyboards import (
    content_plan_menu_kb,
    plan_topics_prompt_kb,
    generate_plan_covers_kb,
    carousel_kb,
    carousel_edit_text_kb,
    carousel_cover_kb,
    topic_added_kb,
    confirm_delete_queue_kb,
    plan_ready_notification_kb,
    plan_chat_cancel_kb,
    plan_covers_kb,
)
from utils.plan_utils import get_auto_publish_limits, get_menu_flags
from utils.html_sanitizer import sanitize_html
from config.settings import config

logger = structlog.get_logger()
router = Router()


# ============================================================
#  УТИЛИТЫ
# ============================================================

async def _safe_callback_answer(callback: CallbackQuery, text: str = None, show_alert: bool = False):
    """Безопасный ответ на callback query (не падает на протухших запросах)"""
    try:
        await callback.answer(text, show_alert=show_alert)
    except Exception:
        pass


def _parse_media_info(media_info):
    """Parse media_info to dict"""
    if isinstance(media_info, str):
        return json.loads(media_info)
    return media_info


def _has_photo(media_info) -> bool:
    """Check if media_info has photos"""
    if not media_info:
        return False
    if media_info.get("type") == "album":
        return any(item.get("type") == "photo" for item in media_info.get("items", []))
    return media_info.get("type") == "photo" and bool(media_info.get("file_id"))


def _get_first_photo_file_id(media_info) -> str:
    """Get first photo file_id"""
    if not media_info:
        return ""
    if media_info.get("type") == "album":
        for item in media_info.get("items", []):
            if item.get("type") == "photo":
                return item["file_id"]
    if media_info.get("type") == "photo":
        return media_info.get("file_id", "")
    return ""


def format_carousel_caption(queue_item: dict, post: dict, position: int, total: int) -> str:
    """Формат текста для карусели"""
    format_type = queue_item.get("format", "")
    scheduled_at = queue_item.get("scheduled_at")

    if scheduled_at:
        tz = ZoneInfo("Europe/Moscow")
        if scheduled_at.tzinfo:
            msk = scheduled_at.astimezone(tz)
        else:
            msk = scheduled_at
        date_str = msk.strftime("%d.%m.%Y — %H:%M МСК")
    else:
        date_str = "не назначено"

    post_text = post.get("final_text") or post.get("generated_text") or ""

    format_icons = {
        "обзор": "📊", "совет": "💡", "кейс": "📈",
        "подборка": "📝", "мнение": "🤔",
    }
    format_icon = format_icons.get(format_type, "📋")

    caption = (
        f"📋 Пост {position} из {total}\n"
        f"📅 {date_str}\n"
        f"{format_icon} Формат: {format_type}\n"
        f"───────────────\n\n"
        f"{post_text}\n\n"
        f"───────────────"
    )
    return caption


# ============================================================
#  МЕНЮ КОНТЕНТ-ПЛАНА
# ============================================================

@router.callback_query(F.data == "autopub:plan")
async def content_plan_menu(callback: CallbackQuery, state: FSMContext):
    """Меню контент-плана"""
    await state.clear()
    chat_id = callback.from_user.id
    user = await UserManager.get_by_chat_id(chat_id)
    if not user:
        await _safe_callback_answer(callback, "Ошибка", show_alert=True)
        return

    user_id = user["id"]
    total = await ContentQueueManager.get_active_queue_count(user_id)

    # Estimate days coverage
    settings = await AutoPublishManager.get_settings(user_id)
    slots_per_week = 0
    if settings and settings.get("schedule"):
        slots_per_week = len(settings["schedule"].get("slots", []))
    days_coverage = ""
    if slots_per_week > 0 and total > 0:
        slots_per_day = slots_per_week / 7
        if slots_per_day > 0:
            days = int(total / slots_per_day)
            days_coverage = f"\nТем хватит на: ~{days} дней"

    text = (
        f"📋 <b>Контент-план</b>\n\n"
        f"В очереди: {total} постов"
        f"{days_coverage}\n\n"
        f"<b>Что здесь можно:</b>\n"
        f"🤖 <b>Сгенерировать план с ИИ</b> — ИИ предложит темы на 7 дней, вы обсудите и подтвердите\n"
        f"📝 <b>Добавить тему</b> — вручную добавить тему, пост сгенерируется автоматически\n"
        f"📄 <b>Мои посты</b> — просмотр, редактирование и управление очередью"
    )

    await callback.message.edit_text(
        text,
        reply_markup=content_plan_menu_kb(),
        parse_mode="HTML",
    )
    await _safe_callback_answer(callback)


# ============================================================
#  AI-ГЕНЕРАЦИЯ ПЛАНА
# ============================================================

@router.callback_query(F.data == "cplan:generate")
async def generate_plan_start(callback: CallbackQuery, state: FSMContext):
    """Начало генерации AI-плана → приветствие + вопрос о темах"""
    await _safe_callback_answer(callback)
    chat_id = callback.from_user.id
    user = await UserManager.get_by_chat_id(chat_id)
    if not user:
        await _safe_callback_answer(callback, "Ошибка", show_alert=True)
        return

    plan = user.get("plan", "free")
    limits = get_auto_publish_limits(plan)

    if not limits.get("allow_ai_plan"):
        await callback.message.edit_text(
            "⚠️ AI-генерация плана доступна на тарифе Про. Добавляйте темы вручную.",
        )
        return

    # Check prerequisites
    agent = await AgentManager.get_agent(user["id"])
    if not agent:
        await callback.message.edit_text("⚠️ Сначала создайте ИИ-агента (🤖 Мой агент).")
        return

    channel = await ChannelManager.get_channel(user["id"])
    if not channel:
        await callback.message.edit_text("⚠️ Сначала привяжите канал (📢 Мой канал).")
        return

    settings = await AutoPublishManager.get_settings(user["id"])
    if not settings or not settings.get("schedule", {}).get("slots"):
        await callback.message.edit_text("⚠️ Сначала настройте расписание публикаций.")
        return

    has_tokens = await UserManager.has_tokens(chat_id)
    if not has_tokens:
        await callback.message.edit_text("⚠️ Недостаточно токенов. Докупите в 💳 Подписка.")
        return

    slots = settings["schedule"]["slots"]
    slots_count = len(slots)

    # Формируем текстовое описание расписания
    day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    schedule_info = ", ".join([
        f"{day_names[s['day']]} {s['time']}" for s in sorted(slots, key=lambda x: (x["day"], x["time"]))
    ])

    # Этап 1: Приветствие + вопрос о темах
    welcome_text = (
        f"🧠 <b>Привет! Я — твой контент-стратег.</b>\n\n"
        f"Помогу составить контент-план на <b>7 дней</b> для твоего канала.\n\n"
        f"<b>Как это работает:</b>\n"
        f"1️⃣ Я предложу темы, учитывая стиль твоего канала\n"
        f"2️⃣ Мы вместе обсудим и скорректируем план\n"
        f"3️⃣ После подтверждения — автоматически сгенерирую все посты\n\n"
        f"📅 Расписание: {schedule_info}\n"
        f"📝 Слотов для публикаций: {slots_count}\n\n"
        f"💡 <b>Есть темы, которые хочешь осветить?</b>\n"
        f"Напиши их сейчас — я учту при составлении плана.\n"
        f"Или нажми кнопку ниже, чтобы я предложил темы сам."
    )

    await callback.message.edit_text(
        welcome_text,
        parse_mode="HTML",
        reply_markup=plan_topics_prompt_kb()
    )

    # Сохраняем данные для последующего запуска сессии
    await state.set_state(ContentPlan.waiting_user_topics)
    await state.update_data(
        plan_user_id=user["id"],
        plan_agent_instructions=agent["instructions"],
        plan_channel_name=channel.get("channel_title", "канал"),
        plan_slots_count=slots_count,
        plan_schedule_info=schedule_info,
    )


async def _launch_plan_session(
    chat_id: int,
    state: FSMContext,
    status_msg,
    user_topics: str = ""
):
    """Запуск сессии планирования (общий код для обоих сценариев)"""
    data = await state.get_data()
    user_id = data.get("plan_user_id")
    agent_instructions = data.get("plan_agent_instructions", "")
    channel_name = data.get("plan_channel_name", "канал")
    slots_count = data.get("plan_slots_count", 7)
    schedule_info = data.get("plan_schedule_info", "")

    now_msk = datetime.now(ZoneInfo("Europe/Moscow"))
    current_date = now_msk.strftime("%d.%m.%Y (%A)")

    try:
        first_reply, session_id = await PlanChatService.start_session(
            chat_id=chat_id,
            user_id=user_id,
            agent_instructions=agent_instructions,
            channel_name=channel_name,
            slots_count=slots_count,
            schedule_info=schedule_info,
            current_date=current_date,
            user_topics=user_topics
        )

        # Сохраняем session_id в FSM
        await state.set_state(ContentPlan.discussing_plan)
        await state.update_data(plan_session_id=session_id)

        # Отправляем первый ответ ИИ + клавиатуру отмены
        await status_msg.edit_text(
            f"🤖 <b>Планирование контента</b>\n\n{first_reply}\n\n"
            f"<i>Обсудите план с ИИ. Когда будете готовы — подтвердите.</i>",
            parse_mode="HTML",
            reply_markup=plan_chat_cancel_kb()
        )
    except Exception as e:
        logger.error("Failed to start plan chat", error=str(e))
        await status_msg.edit_text(
            "❌ Ошибка запуска диалога. Попробуйте позже.",
            reply_markup=content_plan_menu_kb()
        )


@router.message(ContentPlan.waiting_user_topics)
async def handle_user_topics(message: Message, state: FSMContext):
    """Сценарий A: пользователь прислал текст с темами"""
    chat_id = message.from_user.id
    user_topics = message.text
    if not user_topics:
        await message.answer("⚠️ Отправьте темы текстом.")
        return

    await state.update_data(user_topics=user_topics)
    status_msg = await message.answer("⏳ Формирую предложения с учётом ваших тем...")

    await _launch_plan_session(chat_id, state, status_msg, user_topics=user_topics)


@router.callback_query(F.data == "cplan_skip_topics")
async def cb_skip_topics(callback: CallbackQuery, state: FSMContext):
    """Сценарий B: пользователь нажал «Предложи темы сам»"""
    await _safe_callback_answer(callback)

    status_msg = await callback.message.edit_text("⏳ Формирую предложения...")
    chat_id = callback.from_user.id

    await _launch_plan_session(chat_id, state, status_msg)


@router.callback_query(F.data == "cplan_back_to_menu")
async def cb_back_to_menu(callback: CallbackQuery, state: FSMContext):
    """Сценарий C: пользователь нажал «Назад» — возврат в меню"""
    await _safe_callback_answer(callback)
    await state.clear()

    # Перенаправляем в меню контент-плана
    chat_id = callback.from_user.id
    user = await UserManager.get_by_chat_id(chat_id)
    if not user:
        return

    user_id = user["id"]
    total = await ContentQueueManager.get_active_queue_count(user_id)

    settings = await AutoPublishManager.get_settings(user_id)
    slots_per_week = 0
    if settings and settings.get("schedule"):
        slots_per_week = len(settings["schedule"].get("slots", []))
    days_coverage = ""
    if slots_per_week > 0 and total > 0:
        slots_per_day = slots_per_week / 7
        if slots_per_day > 0:
            days = int(total / slots_per_day)
            days_coverage = f"\nТем хватит на: ~{days} дней"

    text = (
        f"📋 <b>Контент-план</b>\n\n"
        f"В очереди: {total} постов"
        f"{days_coverage}\n\n"
        f"<b>Что здесь можно:</b>\n"
        f"🤖 <b>Сгенерировать план с ИИ</b> — ИИ предложит темы на 7 дней, вы обсудите и подтвердите\n"
        f"📝 <b>Добавить тему</b> — вручную добавить тему, пост сгенерируется автоматически\n"
        f"📄 <b>Мои посты</b> — просмотр, редактирование и управление очередью"
    )

    await callback.message.edit_text(
        text,
        reply_markup=content_plan_menu_kb(),
        parse_mode="HTML",
    )


# ============================================================
#  ДИАЛОГ С ИИ ПО КОНТЕНТ-ПЛАНУ
# ============================================================

@router.message(ContentPlan.discussing_plan)
async def handle_plan_chat_message(message: Message, state: FSMContext, bot: Bot):
    """Обработка сообщений пользователя в диалоге по контент-плану"""
    data = await state.get_data()
    session_id = data.get("plan_session_id")

    if not session_id:
        await state.clear()
        await message.answer("⚠️ Сессия не найдена. Начните заново.")
        return

    chat_id = message.from_user.id

    # Извлекаем текст (поддержка голосовых через Whisper)
    user_text = None

    if message.voice or message.audio:
        status = await message.answer("🎤 Распознаю голос...")
        try:
            voice_obj = message.voice or message.audio
            user_text = await transcribe_voice(bot, voice_obj)
            await status.delete()
        except Exception as e:
            logger.error("Whisper transcription failed in plan chat", error=str(e))
            await status.edit_text("❌ Не удалось распознать голос. Напишите текстом.")
            return
        if not user_text:
            await message.answer("❌ Не удалось распознать голос. Напишите текстом.")
            return
    elif message.text:
        user_text = message.text
    else:
        await message.answer("⚠️ Отправьте текст или голосовое сообщение.")
        return

    if not user_text or not user_text.strip():
        await message.answer("⚠️ Пустое сообщение.")
        return

    # Показываем "думаю..."
    status_msg = await message.answer("💭 Думаю...")

    try:
        reply_text, confirmed_plan = await PlanChatService.send_message(
            session_id=session_id,
            user_message=user_text.strip(),
            chat_id=chat_id
        )

        if confirmed_plan:
            # === ПЛАН ПОДТВЕРЖДЁН ===
            # Сохраняем план в FSM для следующего шага (вопрос про обложки)
            await state.clear()
            await state.update_data(confirmed_plan=confirmed_plan)

            await status_msg.edit_text(
                f"✅ <b>План подтверждён!</b>\n\n{reply_text}",
                parse_mode="HTML"
            )

            # Переходим к вопросу про обложки
            await message.answer(
                "🖼 Генерировать AI-обложки к постам?\n"
                "(это займёт больше времени и токенов)",
                reply_markup=plan_covers_kb()
            )
        else:
            # === ОБЫЧНЫЙ ОТВЕТ — продолжаем диалог ===
            await status_msg.edit_text(
                reply_text,
                reply_markup=plan_chat_cancel_kb()
            )
    except Exception as e:
        logger.error("Plan chat message error", error=str(e), session_id=session_id)
        await status_msg.edit_text("❌ Ошибка. Попробуйте отправить сообщение ещё раз.")


@router.callback_query(F.data == "plan_chat_cancel")
async def cb_plan_chat_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена диалога по контент-плану"""
    await _safe_callback_answer(callback, "Планирование отменено")

    data = await state.get_data()
    session_id = data.get("plan_session_id")

    if session_id:
        await PlanChatManager.cancel_session(session_id)

    await state.clear()

    await callback.message.edit_text(
        "❌ Планирование контента отменено.\n"
        "Вы можете начать заново в разделе контент-плана.",
        reply_markup=content_plan_menu_kb()
    )


@router.callback_query(F.data.in_({"plan_covers_yes", "plan_covers_no"}))
async def cb_plan_covers_choice(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Выбор: генерировать обложки или нет — после подтверждения плана через диалог"""
    await _safe_callback_answer(callback)

    with_covers = callback.data == "plan_covers_yes"
    data = await state.get_data()
    confirmed_plan = data.get("confirmed_plan")

    if not confirmed_plan:
        await callback.message.edit_text(
            "⚠️ План не найден. Начните заново.",
            reply_markup=content_plan_menu_kb()
        )
        await state.clear()
        return

    await state.clear()

    topics = confirmed_plan.get("topics", [])
    chat_id = callback.from_user.id
    user = await UserManager.get_by_chat_id(chat_id)
    if not user:
        await callback.message.edit_text("⚠️ Пользователь не найден.")
        return

    user_id = user["id"]
    agent = await AgentManager.get_agent(user_id)
    if not agent:
        await callback.message.edit_text("⚠️ Агент не найден.")
        return

    settings = await AutoPublishManager.get_settings(user_id)
    schedule = settings.get("schedule", {}) if settings else {}

    await callback.message.edit_text(
        f"⏳ Генерирую {len(topics)} постов"
        f"{' с обложками' if with_covers else ''}...\n"
        f"Это может занять несколько минут."
    )

    # Рассчитываем даты для постов
    from services.content_plan_service import calculate_schedule_times
    schedule_times = calculate_schedule_times(schedule, len(topics)) if schedule.get("slots") else []

    agent_model = agent.get("model", "gpt-4o-mini")
    queue_items = []
    errors = 0

    for i, topic_data in enumerate(topics):
        topic = topic_data["topic"]
        fmt = topic_data.get("format", "обзор")

        # Генерация текста поста
        result = await generate_post_for_topic(
            topic=topic,
            format=fmt,
            agent_instructions=agent["instructions"],
            model=agent_model,
        )

        if not result.get("success"):
            logger.error("Post generation failed for plan topic", topic=topic[:50])
            errors += 1
            continue

        post_tokens = result.get("total_tokens", 0)
        await UserManager.spend_tokens(chat_id, post_tokens)

        # Создаём запись поста
        post = await PostManager.create_post(
            user_id=user_id,
            generated_text=result["text"],
            original_text=topic,
            input_tokens=result.get("input_tokens", 0),
            output_tokens=result.get("output_tokens", 0),
        )
        post_id = post["id"]

        # Генерация обложки
        if with_covers:
            cover = await generate_cover_for_post(result["text"], bot, chat_id)
            if cover:
                await PostMediaManager.add_media_item(post_id, cover)

        scheduled_at = schedule_times[i] if i < len(schedule_times) else None

        queue_items.append({
            "topic": topic,
            "format": fmt,
            "post_id": post_id,
            "scheduled_at": scheduled_at,
            "status": "ready",
        })

    # Сохраняем в очередь
    if queue_items:
        await ContentQueueManager.add_items_batch(user_id, queue_items)

    success_count = len(queue_items)

    if success_count > 0:
        error_note = f"\n⚠️ {errors} постов не удалось создать." if errors > 0 else ""
        await callback.message.edit_text(
            f"🎉 Контент-план выполнен!\n"
            f"Сгенерировано {success_count} постов.{error_note}\n"
            f"Они будут опубликованы по расписанию.",
            reply_markup=plan_ready_notification_kb()
        )
    else:
        await callback.message.edit_text(
            "❌ Не удалось создать посты. Попробуйте позже.",
            reply_markup=content_plan_menu_kb()
        )


# ============================================================
#  AI-ГЕНЕРАЦИЯ ПЛАНА (старый флоу без диалога)
# ============================================================

@router.callback_query(F.data.startswith("cplan_gen:"))
async def generate_plan_execute(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Запуск генерации плана"""
    await _safe_callback_answer(callback)

    with_covers = callback.data == "cplan_gen:with_covers"
    chat_id = callback.from_user.id

    user = await UserManager.get_by_chat_id(chat_id)
    if not user:
        return

    user_id = user["id"]
    agent = await AgentManager.get_agent(user_id)
    settings = await AutoPublishManager.get_settings(user_id)

    if not agent or not settings:
        return

    schedule = settings.get("schedule", {})

    # Send status message
    status_msg = await callback.message.edit_text(
        "⏳ Генерирую контент-план...\n\n"
        "📝 Темы: ⏳\n"
        f"🖼 Обложки: {'⏳' if with_covers else 'выкл'}"
    )

    # Устанавливаем state для отслеживания в генераторе
    await state.set_state(ContentPlan.browsing_queue)

    try:
        items = await generate_content_plan(
            bot=bot,
            chat_id=chat_id,
            user_id=user_id,
            agent_instructions=agent["instructions"],
            agent_model=agent.get("model", "gpt-4o-mini"),
            schedule=schedule,
            generate_covers=with_covers,
            status_message=status_msg,
            state=state,
        )

        if items:
            # Проверяем: пользователь ещё в меню?
            current_state = await state.get_state()
            user_in_menu = current_state and "ContentPlan" in str(current_state)

            if user_in_menu:
                # Показать карусель
                try:
                    await status_msg.edit_text(
                        f"✅ Контент-план создан! {len(items)} постов добавлено."
                    )
                except Exception:
                    pass
                await _show_carousel_item(chat_id, state, 1, user_id, bot)
            else:
                # Пользователь ушёл — одно уведомление с кнопкой
                try:
                    await status_msg.delete()
                except Exception:
                    pass
                try:
                    await bot.send_message(
                        chat_id,
                        f"✅ Контент-план готов! {len(items)} постов создано.",
                        reply_markup=plan_ready_notification_kb(),
                    )
                except Exception:
                    pass
        else:
            await status_msg.edit_text(
                "❌ Не удалось создать контент-план. Попробуйте позже.",
                reply_markup=content_plan_menu_kb(),
            )
    except Exception as e:
        logger.error("Plan generation error", error=str(e))
        try:
            await status_msg.edit_text(
                "❌ Ошибка при генерации плана. Попробуйте позже.",
                reply_markup=content_plan_menu_kb(),
            )
        except Exception:
            pass


# ============================================================
#  РУЧНОЕ ДОБАВЛЕНИЕ ТЕМЫ
# ============================================================

@router.callback_query(F.data == "cplan:add_topic")
async def add_topic_start(callback: CallbackQuery, state: FSMContext):
    """Начало добавления темы"""
    chat_id = callback.from_user.id
    user = await UserManager.get_by_chat_id(chat_id)
    if not user:
        await _safe_callback_answer(callback, "Ошибка", show_alert=True)
        return

    plan = user.get("plan", "free")
    limits = get_auto_publish_limits(plan)

    # Check queue size
    current_count = await ContentQueueManager.get_active_queue_count(user["id"])
    max_size = limits.get("max_queue_size", 10)
    if current_count >= max_size:
        await _safe_callback_answer(
            callback,
            f"⚠️ Максимум {max_size} постов в очереди. Удалите старые или обновите тариф.",
            show_alert=True,
        )
        return

    # Check prerequisites
    agent = await AgentManager.get_agent(user["id"])
    if not agent:
        await _safe_callback_answer(callback, "⚠️ Сначала создайте агента (🤖 Мой агент)", show_alert=True)
        return

    has_tokens = await UserManager.has_tokens(chat_id)
    if not has_tokens:
        await _safe_callback_answer(callback, "⚠️ Недостаточно токенов", show_alert=True)
        return

    await state.set_state(ContentPlan.adding_topic)
    await state.update_data(insert_after=None)

    try:
        await callback.message.edit_text(
            "📝 Напишите тему для поста.\n\n"
            "Примеры:\n"
            "• Топ-5 трендов AI в 2026\n"
            "• Как выбрать CRM для малого бизнеса\n"
            "• Кейс: автоматизация ресторана"
        )
    except Exception:
        await callback.message.answer(
            "📝 Напишите тему для поста.\n\n"
            "Примеры:\n"
            "• Топ-5 трендов AI в 2026\n"
            "• Как выбрать CRM для малого бизнеса\n"
            "• Кейс: автоматизация ресторана"
        )
    await _safe_callback_answer(callback)


@router.message(ContentPlan.adding_topic)
async def process_add_topic(message: Message, state: FSMContext, bot: Bot):
    """Обработка введённой темы"""
    chat_id = message.from_user.id

    # Get text from message or voice
    if message.voice:
        topic = await transcribe_voice(bot, message.voice)
        if not topic:
            await message.answer("⚠️ Не удалось распознать голос. Попробуйте текстом.")
            return
    else:
        topic = message.text
        if not topic:
            await message.answer("⚠️ Введите тему текстом.")
            return

    user = await UserManager.get_by_chat_id(chat_id)
    if not user:
        await message.answer("Ошибка")
        return

    user_id = user["id"]
    agent = await AgentManager.get_agent(user_id)
    if not agent:
        await message.answer("⚠️ Агент не найден")
        await state.clear()
        return

    status_msg = await message.answer("⏳ Генерирую пост по теме...")

    # Generate post
    result = await generate_post_for_topic(
        topic=topic,
        format="обзор",
        agent_instructions=agent["instructions"],
        model=agent.get("model", "gpt-4o-mini"),
    )

    if not result.get("success"):
        await status_msg.edit_text("❌ Не удалось создать пост. Попробуйте другую тему.")
        return

    tokens = result.get("total_tokens", 0)
    await UserManager.spend_tokens(chat_id, tokens)

    # Create post
    post = await PostManager.create_post(
        user_id=user_id,
        generated_text=result["text"],
        original_text=topic,
        input_tokens=result.get("input_tokens", 0),
        output_tokens=result.get("output_tokens", 0),
    )

    # Generate cover if settings say so
    settings = await AutoPublishManager.get_settings(user_id)
    if settings and settings.get("generate_covers", True):
        cover = await generate_cover_for_post(result["text"], bot, chat_id)
        if cover:
            await PostMediaManager.add_media_item(post["id"], cover)

    # Calculate scheduled_at
    schedule = settings.get("schedule", {}) if settings else {}
    scheduled_at = None
    if schedule.get("slots"):
        from services.content_plan_service import calculate_schedule_times
        # Get the next available slot after all existing items
        existing_count = await ContentQueueManager.get_active_queue_count(user_id)
        times = calculate_schedule_times(schedule, existing_count + 1)
        if times:
            scheduled_at = times[-1]

    # Check if inserting after specific position
    data = await state.get_data()
    insert_after = data.get("insert_after")

    if insert_after is not None:
        queue_item = await ContentQueueManager.insert_after(
            user_id=user_id,
            after_position=insert_after,
            topic=topic,
            format="обзор",
            post_id=post["id"],
            scheduled_at=scheduled_at,
            status="ready",
        )
        # Recalculate all scheduled_at
        if schedule.get("slots"):
            await ContentQueueManager.recalculate_scheduled_at(user_id, schedule)
        position = queue_item["position"]
    else:
        queue_item = await ContentQueueManager.add_item(
            user_id=user_id,
            topic=topic,
            format="обзор",
            post_id=post["id"],
            scheduled_at=scheduled_at,
            status="ready",
        )
        position = queue_item["position"]

    await state.clear()

    date_str = ""
    if scheduled_at:
        tz = ZoneInfo("Europe/Moscow")
        dt = scheduled_at.astimezone(tz)
        date_str = f"\n📅 Запланировано: {dt.strftime('%d.%m.%Y %H:%M')} МСК"

    await status_msg.edit_text(
        f"✅ Тема добавлена в очередь! (позиция #{position})"
        f"{date_str}",
        reply_markup=topic_added_kb(),
    )


# ============================================================
#  КАРУСЕЛЬ — ПРОСМОТР ОЧЕРЕДИ
# ============================================================

@router.callback_query(F.data == "cplan:browse")
async def browse_queue(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Начать просмотр очереди"""
    chat_id = callback.from_user.id
    user = await UserManager.get_by_chat_id(chat_id)
    if not user:
        await _safe_callback_answer(callback, "Ошибка", show_alert=True)
        return

    user_id = user["id"]
    count = await ContentQueueManager.get_active_queue_count(user_id)
    if count == 0:
        await _safe_callback_answer(callback, "Очередь пуста. Сгенерируйте контент-план.", show_alert=True)
        return

    await state.set_state(ContentPlan.browsing_queue)
    await _show_carousel_item(chat_id, state, 1, user_id, bot)
    await _safe_callback_answer(callback)


async def _show_carousel_item(chat_id: int, state: FSMContext, position: int, user_id: int, bot: Bot):
    """Показать пост в карусели"""
    data = await state.get_data()
    old_msg_id = data.get("carousel_message_id")
    old_media_type = data.get("carousel_media_type")

    # Get active queue items sorted by position
    queue = await ContentQueueManager.get_queue(user_id)
    active_items = [q for q in queue if q["status"] in ("pending", "ready")]

    if not active_items:
        try:
            if old_msg_id:
                await bot.delete_message(chat_id, old_msg_id)
        except Exception:
            pass
        await bot.send_message(chat_id, "📋 Очередь пуста.",
                               reply_markup=content_plan_menu_kb())
        await state.update_data(carousel_message_id=None, carousel_media_type=None)
        return

    total = len(active_items)
    position = max(1, min(position, total))

    item = active_items[position - 1]
    queue_id = item["id"]
    post_id = item.get("post_id")

    post = None
    has_photo = False
    media_info = None

    if post_id:
        post = await PostManager.get_post(post_id)
        if post:
            media_info = post.get("media_info")
            if isinstance(media_info, str):
                media_info = json.loads(media_info)
            has_photo = _has_photo(media_info)

    if not post:
        post = {"final_text": "", "generated_text": f"[Пост не сгенерирован]\nТема: {item.get('topic', '')}"}

    text = format_carousel_caption(item, post, position, total)
    kb = carousel_kb(queue_id, position, total)
    new_media_type = "photo" if has_photo else "text"

    # Sanitize
    text = sanitize_html(text)

    # Try to edit existing message
    if old_msg_id and old_media_type == new_media_type:
        if new_media_type == "text":
            try:
                await bot.edit_message_text(
                    text, chat_id, old_msg_id,
                    reply_markup=kb, parse_mode="HTML"
                )
                await state.update_data(
                    carousel_message_id=old_msg_id,
                    carousel_media_type="text",
                    carousel_position=position,
                )
                return
            except Exception:
                pass
        elif new_media_type == "photo":
            try:
                file_id = _get_first_photo_file_id(media_info)
                media = InputMediaPhoto(media=file_id, caption=text, parse_mode="HTML")
                await bot.edit_message_media(media, chat_id, old_msg_id, reply_markup=kb)
                await state.update_data(
                    carousel_message_id=old_msg_id,
                    carousel_media_type="photo",
                    carousel_position=position,
                )
                return
            except Exception:
                pass

    # Fallback: delete old + send new
    if old_msg_id:
        try:
            await bot.delete_message(chat_id, old_msg_id)
        except Exception:
            pass

    if has_photo:
        file_id = _get_first_photo_file_id(media_info)
        if len(text) <= 1024:
            msg = await bot.send_photo(
                chat_id, file_id, caption=text,
                reply_markup=kb, parse_mode="HTML"
            )
        else:
            await bot.send_photo(chat_id, file_id)
            msg = await bot.send_message(
                chat_id, text,
                reply_markup=kb, parse_mode="HTML"
            )
    else:
        msg = await bot.send_message(
            chat_id, text,
            reply_markup=kb, parse_mode="HTML"
        )

    await state.update_data(
        carousel_message_id=msg.message_id,
        carousel_media_type=new_media_type,
        carousel_position=position,
    )


# ============================================================
#  НАВИГАЦИЯ КАРУСЕЛИ
# ============================================================

@router.callback_query(F.data.startswith("cplan_nav:"))
async def carousel_navigate(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Навигация по карусели"""
    parts = callback.data.split(":")
    action = parts[1]
    current = int(parts[2]) if len(parts) > 2 else 1

    chat_id = callback.from_user.id
    user = await UserManager.get_by_chat_id(chat_id)
    if not user:
        await _safe_callback_answer(callback, "Ошибка", show_alert=True)
        return

    user_id = user["id"]

    if action == "goto":
        # Переход к конкретному посту — запрашиваем номер
        total = await ContentQueueManager.get_active_queue_count(user_id)
        if total <= 1:
            await _safe_callback_answer(callback, "В очереди только 1 пост", show_alert=True)
            return

        await state.set_state(ContentPlan.goto_position)
        await state.update_data(goto_total=total, goto_current=current)

        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="cplan_nav:goto_cancel")]
        ])

        try:
            await callback.message.edit_text(
                f"🔢 Введите номер поста (1—{total}):",
                reply_markup=cancel_kb
            )
        except Exception:
            await callback.message.answer(
                f"🔢 Введите номер поста (1—{total}):",
                reply_markup=cancel_kb
            )
        await _safe_callback_answer(callback)
        return

    if action == "goto_cancel":
        # Отмена перехода — возврат к карусели
        data = await state.get_data()
        pos = data.get("goto_current", 1)
        await state.set_state(ContentPlan.browsing_queue)
        await _show_carousel_item(chat_id, state, pos, user_id, bot)
        await _safe_callback_answer(callback)
        return

    if action == "prev":
        new_pos = max(1, current - 1)
    elif action == "next":
        new_pos = current + 1
    elif action == "stay":
        # Stay on the item by queue_id
        queue_id = int(parts[2])
        item = await ContentQueueManager.get_item(queue_id)
        if item:
            # Find position among active items
            queue = await ContentQueueManager.get_queue(user_id)
            active = [q for q in queue if q["status"] in ("pending", "ready")]
            for i, q in enumerate(active, 1):
                if q["id"] == queue_id:
                    new_pos = i
                    break
            else:
                new_pos = 1
        else:
            new_pos = 1
    else:
        new_pos = 1

    await state.set_state(ContentPlan.browsing_queue)
    await _show_carousel_item(chat_id, state, new_pos, user_id, bot)
    await _safe_callback_answer(callback)


@router.message(ContentPlan.goto_position)
async def process_goto_position(message: Message, state: FSMContext, bot: Bot):
    """Обработка ввода номера поста для перехода"""
    chat_id = message.from_user.id
    data = await state.get_data()
    total = data.get("goto_total", 1)

    text = message.text
    if not text or not text.strip().isdigit():
        await message.answer(f"❌ Введите число от 1 до {total}")
        return

    position = int(text.strip())
    if position < 1 or position > total:
        await message.answer(f"❌ Введите число от 1 до {total}")
        return

    user = await UserManager.get_by_chat_id(chat_id)
    if not user:
        await state.clear()
        return

    await state.set_state(ContentPlan.browsing_queue)
    await _show_carousel_item(chat_id, state, position, user["id"], bot)


# ============================================================
#  РЕДАКТИРОВАНИЕ ТЕКСТА
# ============================================================

@router.callback_query(F.data.startswith("cplan_edit:"))
async def edit_post_menu(callback: CallbackQuery, state: FSMContext):
    """Меню редактирования текста"""
    queue_id = int(callback.data.split(":")[1])

    try:
        await callback.message.edit_reply_markup(
            reply_markup=carousel_edit_text_kb(queue_id)
        )
    except Exception:
        await callback.message.answer(
            "✏️ Как изменить пост?",
            reply_markup=carousel_edit_text_kb(queue_id),
        )
    await _safe_callback_answer(callback)


@router.callback_query(F.data.startswith("cplan_textedit:custom:"))
async def edit_custom(callback: CallbackQuery, state: FSMContext):
    """Свои правки — запрос инструкции"""
    queue_id = int(callback.data.split(":")[2])
    await state.set_state(ContentPlan.editing_post_text)
    await state.update_data(editing_queue_id=queue_id)

    try:
        await callback.message.edit_text(
            "✏️ Напишите что изменить.\n"
            "Например: «Сделай короче», «Добавь цифры», «Измени тон на более дружеский»"
        )
    except Exception:
        await callback.message.answer(
            "✏️ Напишите что изменить.\n"
            "Например: «Сделай короче», «Добавь цифры», «Измени тон на более дружеский»"
        )
    await _safe_callback_answer(callback)


@router.message(ContentPlan.editing_post_text)
async def process_edit_text(message: Message, state: FSMContext, bot: Bot):
    """Обработка правок текста"""
    chat_id = message.from_user.id

    # Get instruction
    if message.voice:
        instruction = await transcribe_voice(bot, message.voice)
        if not instruction:
            await message.answer("⚠️ Не удалось распознать голос.")
            return
    else:
        instruction = message.text
        if not instruction:
            return

    data = await state.get_data()
    queue_id = data.get("editing_queue_id")
    if not queue_id:
        await state.clear()
        return

    item = await ContentQueueManager.get_item(queue_id)
    if not item:
        await message.answer("⚠️ Пост не найден")
        await state.clear()
        return

    post = await PostManager.get_post(item["post_id"])
    if not post:
        await message.answer("⚠️ Пост не найден")
        await state.clear()
        return

    user = await UserManager.get_by_chat_id(chat_id)
    agent = await AgentManager.get_agent(user["id"])

    current_text = post.get("final_text") or post.get("generated_text") or ""

    status_msg = await message.answer("⏳ Редактирую пост...")

    result = await openai_service.edit_content(
        current_text=current_text,
        edit_instruction=instruction,
        agent_instructions=agent["instructions"] if agent else "",
        model=agent.get("model", "gpt-4o-mini") if agent else "gpt-4o-mini",
    )

    if not result.get("success"):
        await status_msg.edit_text("❌ Ошибка редактирования. Попробуйте ещё раз.")
        return

    tokens = result.get("total_tokens", 0)
    await UserManager.spend_tokens(chat_id, tokens)

    await PostManager.update_post_text(
        post_id=item["post_id"],
        new_text=result["text"],
        input_tokens=result.get("input_tokens", 0),
        output_tokens=result.get("output_tokens", 0),
    )

    await status_msg.delete()
    await state.set_state(ContentPlan.browsing_queue)

    # Find position and show carousel
    user_id = user["id"]
    queue = await ContentQueueManager.get_queue(user_id)
    active = [q for q in queue if q["status"] in ("pending", "ready")]
    pos = 1
    for i, q in enumerate(active, 1):
        if q["id"] == queue_id:
            pos = i
            break

    await _show_carousel_item(chat_id, state, pos, user_id, bot)


@router.callback_query(F.data.startswith("cplan_textedit:regen:"))
async def regen_post(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Перегенерировать пост"""
    await _safe_callback_answer(callback)

    queue_id = int(callback.data.split(":")[2])
    chat_id = callback.from_user.id

    item = await ContentQueueManager.get_item(queue_id)
    if not item:
        return

    user = await UserManager.get_by_chat_id(chat_id)
    agent = await AgentManager.get_agent(user["id"])

    topic = item.get("topic", "")
    fmt = item.get("format", "обзор")

    try:
        await callback.message.edit_text("⏳ Перегенерирую пост...")
    except Exception:
        pass

    result = await generate_post_for_topic(
        topic=topic,
        format=fmt,
        agent_instructions=agent["instructions"] if agent else "",
        model=agent.get("model", "gpt-4o-mini") if agent else "gpt-4o-mini",
    )

    if not result.get("success"):
        await callback.message.edit_text("❌ Ошибка. Попробуйте позже.")
        return

    tokens = result.get("total_tokens", 0)
    await UserManager.spend_tokens(chat_id, tokens)

    await PostManager.update_post_text(
        post_id=item["post_id"],
        new_text=result["text"],
        input_tokens=result.get("input_tokens", 0),
        output_tokens=result.get("output_tokens", 0),
    )

    # Show updated carousel
    user_id = user["id"]
    queue = await ContentQueueManager.get_queue(user_id)
    active = [q for q in queue if q["status"] in ("pending", "ready")]
    pos = 1
    for i, q in enumerate(active, 1):
        if q["id"] == queue_id:
            pos = i
            break

    await state.set_state(ContentPlan.browsing_queue)
    await _show_carousel_item(chat_id, state, pos, user_id, bot)


@router.callback_query(F.data.startswith("cplan_textedit:newtopic:"))
async def change_topic(callback: CallbackQuery, state: FSMContext):
    """Сменить тему"""
    queue_id = int(callback.data.split(":")[2])
    await state.set_state(ContentPlan.changing_topic)
    await state.update_data(changing_queue_id=queue_id)

    try:
        await callback.message.edit_text("📋 Введите новую тему:")
    except Exception:
        await callback.message.answer("📋 Введите новую тему:")
    await _safe_callback_answer(callback)


@router.message(ContentPlan.changing_topic)
async def process_change_topic(message: Message, state: FSMContext, bot: Bot):
    """Обработка смены темы"""
    chat_id = message.from_user.id
    topic = message.text
    if not topic:
        return

    data = await state.get_data()
    queue_id = data.get("changing_queue_id")
    if not queue_id:
        await state.clear()
        return

    item = await ContentQueueManager.get_item(queue_id)
    if not item:
        await message.answer("⚠️ Пост не найден")
        await state.clear()
        return

    user = await UserManager.get_by_chat_id(chat_id)
    agent = await AgentManager.get_agent(user["id"])

    status_msg = await message.answer("⏳ Генерирую пост на новую тему...")

    # Update topic in queue
    await ContentQueueManager.update_topic(queue_id, topic)

    # Generate new post
    result = await generate_post_for_topic(
        topic=topic,
        format="обзор",
        agent_instructions=agent["instructions"] if agent else "",
        model=agent.get("model", "gpt-4o-mini") if agent else "gpt-4o-mini",
    )

    if not result.get("success"):
        await status_msg.edit_text("❌ Ошибка генерации.")
        await state.clear()
        return

    tokens = result.get("total_tokens", 0)
    await UserManager.spend_tokens(chat_id, tokens)

    await PostManager.update_post_text(
        post_id=item["post_id"],
        new_text=result["text"],
        input_tokens=result.get("input_tokens", 0),
        output_tokens=result.get("output_tokens", 0),
    )

    # Optionally regenerate cover
    settings = await AutoPublishManager.get_settings(user["id"])
    if settings and settings.get("generate_covers", True):
        cover = await generate_cover_for_post(result["text"], bot, chat_id)
        if cover:
            await PostMediaManager.clear_media(item["post_id"])
            await PostMediaManager.add_media_item(item["post_id"], cover)

    await status_msg.delete()

    # Return to carousel
    user_id = user["id"]
    queue = await ContentQueueManager.get_queue(user_id)
    active = [q for q in queue if q["status"] in ("pending", "ready")]
    pos = 1
    for i, q in enumerate(active, 1):
        if q["id"] == queue_id:
            pos = i
            break

    await state.set_state(ContentPlan.browsing_queue)
    await _show_carousel_item(chat_id, state, pos, user_id, bot)


# ============================================================
#  УПРАВЛЕНИЕ ОБЛОЖКОЙ
# ============================================================

@router.callback_query(F.data.startswith("cplan_cover:"))
async def cover_menu(callback: CallbackQuery, state: FSMContext):
    """Меню управления обложкой"""
    queue_id = int(callback.data.split(":")[1])

    item = await ContentQueueManager.get_item(queue_id)
    if not item or not item.get("post_id"):
        await _safe_callback_answer(callback, "Пост не найден", show_alert=True)
        return

    post = await PostManager.get_post(item["post_id"])
    media_info = _parse_media_info(post.get("media_info")) if post else None
    has_cover = _has_photo(media_info)

    cover_status = "✅ AI-обложка" if has_cover else "❌ Нет обложки"

    try:
        await callback.message.edit_reply_markup(
            reply_markup=carousel_cover_kb(queue_id, has_cover)
        )
    except Exception:
        await callback.message.answer(
            f"🖼 Обложка поста\n\nТекущая: {cover_status}",
            reply_markup=carousel_cover_kb(queue_id, has_cover),
        )
    await _safe_callback_answer(callback)


@router.callback_query(F.data.startswith("cplan_cover_auto:"))
async def cover_auto_generate(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Авто-генерация обложки"""
    await _safe_callback_answer(callback)

    queue_id = int(callback.data.split(":")[1])
    chat_id = callback.from_user.id

    item = await ContentQueueManager.get_item(queue_id)
    if not item or not item.get("post_id"):
        return

    post = await PostManager.get_post(item["post_id"])
    post_text = post.get("final_text") or post.get("generated_text") or ""

    try:
        await callback.message.edit_text("⏳ Генерирую обложку...")
    except Exception:
        pass

    cover = await generate_cover_for_post(post_text, bot, chat_id)
    if cover:
        await PostMediaManager.clear_media(item["post_id"])
        await PostMediaManager.add_media_item(item["post_id"], cover)

    # Return to carousel
    user = await UserManager.get_by_chat_id(chat_id)
    user_id = user["id"]
    queue = await ContentQueueManager.get_queue(user_id)
    active = [q for q in queue if q["status"] in ("pending", "ready")]
    pos = 1
    for i, q in enumerate(active, 1):
        if q["id"] == queue_id:
            pos = i
            break

    await state.set_state(ContentPlan.browsing_queue)
    await _show_carousel_item(chat_id, state, pos, user_id, bot)


@router.callback_query(F.data.startswith("cplan_cover_prompt:"))
async def cover_custom_prompt(callback: CallbackQuery, state: FSMContext):
    """Свой промт для обложки"""
    queue_id = int(callback.data.split(":")[1])
    await state.set_state(ContentPlan.waiting_cover_prompt)
    await state.update_data(cover_queue_id=queue_id)

    try:
        await callback.message.edit_text("🎨 Опишите картинку:")
    except Exception:
        await callback.message.answer("🎨 Опишите картинку:")
    await _safe_callback_answer(callback)


@router.message(ContentPlan.waiting_cover_prompt)
async def process_cover_prompt(message: Message, state: FSMContext, bot: Bot):
    """Генерация обложки по промту"""
    chat_id = message.from_user.id

    if message.voice:
        prompt = await transcribe_voice(bot, message.voice)
        if not prompt:
            await message.answer("⚠️ Не удалось распознать голос.")
            return
    else:
        prompt = message.text
        if not prompt:
            return

    data = await state.get_data()
    queue_id = data.get("cover_queue_id")
    if not queue_id:
        await state.clear()
        return

    item = await ContentQueueManager.get_item(queue_id)
    if not item or not item.get("post_id"):
        await message.answer("⚠️ Пост не найден")
        await state.clear()
        return

    status_msg = await message.answer("⏳ Генерирую обложку...")

    cover = await image_service.generate_image(prompt=prompt, bot=bot, chat_id=chat_id)
    if cover:
        await PostMediaManager.clear_media(item["post_id"])
        await PostMediaManager.add_media_item(item["post_id"], cover)
        await status_msg.delete()
    else:
        await status_msg.edit_text("❌ Не удалось создать обложку.")
        return

    # Return to carousel
    user = await UserManager.get_by_chat_id(chat_id)
    user_id = user["id"]
    queue = await ContentQueueManager.get_queue(user_id)
    active = [q for q in queue if q["status"] in ("pending", "ready")]
    pos = 1
    for i, q in enumerate(active, 1):
        if q["id"] == queue_id:
            pos = i
            break

    await state.set_state(ContentPlan.browsing_queue)
    await _show_carousel_item(chat_id, state, pos, user_id, bot)


@router.callback_query(F.data.startswith("cplan_cover_upload:"))
async def cover_upload_start(callback: CallbackQuery, state: FSMContext):
    """Загрузка своего фото"""
    queue_id = int(callback.data.split(":")[1])
    await state.set_state(ContentPlan.waiting_cover_upload)
    await state.update_data(cover_queue_id=queue_id)

    try:
        await callback.message.edit_text("📎 Отправьте фото:")
    except Exception:
        await callback.message.answer("📎 Отправьте фото:")
    await _safe_callback_answer(callback)


@router.message(ContentPlan.waiting_cover_upload, F.photo)
async def process_cover_upload(message: Message, state: FSMContext, bot: Bot):
    """Обработка загруженного фото"""
    chat_id = message.from_user.id
    data = await state.get_data()
    queue_id = data.get("cover_queue_id")
    if not queue_id:
        await state.clear()
        return

    item = await ContentQueueManager.get_item(queue_id)
    if not item or not item.get("post_id"):
        await message.answer("⚠️ Пост не найден")
        await state.clear()
        return

    photo = message.photo[-1]
    cover_item = {
        "type": "photo",
        "file_id": photo.file_id,
        "file_unique_id": photo.file_unique_id,
        "source": "user_upload",
    }

    await PostMediaManager.clear_media(item["post_id"])
    await PostMediaManager.add_media_item(item["post_id"], cover_item)

    # Return to carousel
    user = await UserManager.get_by_chat_id(chat_id)
    user_id = user["id"]
    queue = await ContentQueueManager.get_queue(user_id)
    active = [q for q in queue if q["status"] in ("pending", "ready")]
    pos = 1
    for i, q in enumerate(active, 1):
        if q["id"] == queue_id:
            pos = i
            break

    await state.set_state(ContentPlan.browsing_queue)
    await _show_carousel_item(chat_id, state, pos, user_id, bot)


@router.callback_query(F.data.startswith("cplan_cover_remove:"))
async def cover_remove(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Убрать обложку"""
    queue_id = int(callback.data.split(":")[1])
    chat_id = callback.from_user.id

    item = await ContentQueueManager.get_item(queue_id)
    if not item or not item.get("post_id"):
        await _safe_callback_answer(callback, "Пост не найден", show_alert=True)
        return

    await PostMediaManager.clear_media(item["post_id"])

    user = await UserManager.get_by_chat_id(chat_id)
    user_id = user["id"]
    queue = await ContentQueueManager.get_queue(user_id)
    active = [q for q in queue if q["status"] in ("pending", "ready")]
    pos = 1
    for i, q in enumerate(active, 1):
        if q["id"] == queue_id:
            pos = i
            break

    await state.set_state(ContentPlan.browsing_queue)
    await _show_carousel_item(chat_id, state, pos, user_id, bot)
    await _safe_callback_answer(callback, "Обложка удалена")


# ============================================================
#  УДАЛЕНИЕ ИЗ ОЧЕРЕДИ
# ============================================================

@router.callback_query(F.data.startswith("cplan_delete:"))
async def delete_from_queue(callback: CallbackQuery, state: FSMContext):
    """Запрос подтверждения удаления"""
    queue_id = int(callback.data.split(":")[1])

    try:
        await callback.message.edit_reply_markup(
            reply_markup=confirm_delete_queue_kb(queue_id)
        )
    except Exception:
        pass
    await _safe_callback_answer(callback, "Подтвердите удаление")


@router.callback_query(F.data.startswith("cplan_confirm_del:"))
async def confirm_delete(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Подтверждение удаления"""
    queue_id = int(callback.data.split(":")[1])
    chat_id = callback.from_user.id

    item = await ContentQueueManager.get_item(queue_id)
    if not item:
        await _safe_callback_answer(callback, "Не найдено", show_alert=True)
        return

    user_id = item["user_id"]
    await ContentQueueManager.delete_item(queue_id)

    # Recalculate scheduled_at
    settings = await AutoPublishManager.get_settings(user_id)
    if settings and settings.get("schedule"):
        await ContentQueueManager.recalculate_scheduled_at(user_id, settings["schedule"])

    # Navigate to next/prev
    queue = await ContentQueueManager.get_queue(user_id)
    active = [q for q in queue if q["status"] in ("pending", "ready")]

    if not active:
        try:
            await callback.message.edit_text(
                "📋 Очередь пуста.",
                reply_markup=content_plan_menu_kb(),
            )
        except Exception:
            pass
        await _safe_callback_answer(callback, "Удалено")
        return

    data = await state.get_data()
    pos = data.get("carousel_position", 1)
    pos = min(pos, len(active))

    await state.set_state(ContentPlan.browsing_queue)
    await _show_carousel_item(chat_id, state, pos, user_id, bot)
    await _safe_callback_answer(callback, "Удалено")


# ============================================================
#  ВСТАВКА НОВОЙ ТЕМЫ
# ============================================================

@router.callback_query(F.data.startswith("cplan_insert:"))
async def insert_topic(callback: CallbackQuery, state: FSMContext):
    """Вставить тему после текущего поста"""
    queue_id = int(callback.data.split(":")[1])

    item = await ContentQueueManager.get_item(queue_id)
    if not item:
        await _safe_callback_answer(callback, "Не найдено", show_alert=True)
        return

    await state.set_state(ContentPlan.adding_topic)
    await state.update_data(insert_after=item["position"])

    try:
        await callback.message.edit_text(
            f"📝 Введите тему нового поста (вставится после #{item['position']}):"
        )
    except Exception:
        await callback.message.answer(
            f"📝 Введите тему нового поста (вставится после #{item['position']}):"
        )
    await _safe_callback_answer(callback)
