"""Фоновый сервис авто-публикации"""

import json
import asyncio
import structlog
from datetime import datetime, timezone, timedelta
from typing import Set
from zoneinfo import ZoneInfo
from aiogram import Bot

from database.managers.auto_publish_manager import AutoPublishManager
from database.managers.content_queue_manager import ContentQueueManager
from database.managers.post_manager import PostManager
from database.managers.user_manager import UserManager
from database.managers.channel_manager import ChannelManager
from database.managers.agent_manager import AgentManager
from services.channel_service import publish_post
from services.content_plan_service import generate_content_plan
from bot.keyboards.keyboards import review_post_kb
from utils.html_sanitizer import sanitize_html
from config.settings import config

logger = structlog.get_logger()

CHECK_INTERVAL = 60  # секунд
REVIEW_REMINDER_INTERVAL = 30 * 60  # 30 минут
MAX_REVIEW_REMINDERS = 3
MIN_PROCESS_INTERVAL = 5 * 60  # 5 минут между обработками одного пользователя

# In-memory защита от параллельной обработки одного пользователя
_processing_users: Set[int] = set()


async def run_auto_publisher(bot: Bot):
    """Бесконечный цикл авто-публикации"""
    logger.info("Auto-publisher started")

    while True:
        try:
            await _process_auto_publish(bot)
            await _send_review_reminders(bot)
        except Exception as e:
            logger.error("Auto-publisher error", error=str(e))

        await asyncio.sleep(CHECK_INTERVAL)


def _is_slot_now(schedule: dict) -> bool:
    """Проверить, попадает ли текущее время в слот расписания (с точностью до минуты)"""
    slots = schedule.get("slots", [])
    if not slots:
        return False

    tz_name = schedule.get("timezone", "Europe/Moscow")
    tz = ZoneInfo(tz_name)
    now_local = datetime.now(timezone.utc).astimezone(tz)

    current_weekday = now_local.weekday()
    current_time = now_local.strftime("%H:%M")

    for slot in slots:
        if slot["day"] == current_weekday and slot["time"] == current_time:
            return True

    return False


async def _process_auto_publish(bot: Bot):
    """Основная логика авто-публикации"""
    active_settings = await AutoPublishManager.get_active_settings()

    if not active_settings:
        return

    for settings in active_settings:
        try:
            await _process_user_auto_publish(bot, settings)
        except Exception as e:
            logger.error("Auto-publish error for user",
                         user_id=settings.get("user_id"), error=str(e))


async def _process_user_auto_publish(bot: Bot, settings: dict):
    """Обработка авто-публикации для конкретного пользователя"""
    user_id = settings["user_id"]
    chat_id = settings["chat_id"]
    schedule = settings.get("schedule", {})
    moderation = settings.get("moderation", "review")
    on_empty = settings.get("on_empty", "pause")

    # 1. Защита от одновременной обработки
    if user_id in _processing_users:
        logger.debug("Scheduler tick: user already processing", user_id=user_id)
        return
    _processing_users.add(user_id)

    try:
        # 2. Проверяем что сейчас время слота
        is_slot = _is_slot_now(schedule)
        if not is_slot:
            logger.debug("Scheduler tick: not slot time", user_id=user_id)
            return

        # 3. Проверяем last_processed_at (не чаще раз в 5 минут)
        last_processed = settings.get("last_processed_at")
        if last_processed:
            if last_processed.tzinfo is None:
                last_processed = last_processed.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - last_processed).total_seconds()
            if elapsed < MIN_PROCESS_INTERVAL:
                logger.debug("Scheduler tick: too soon since last process",
                             user_id=user_id, elapsed_sec=int(elapsed))
                return

        # 4. Проверяем нет ли уже поста в review
        review_items = await ContentQueueManager.get_items_for_review(user_id)
        if review_items:
            logger.info("Scheduler tick: waiting for review response",
                        user_id=user_id, review_count=len(review_items))
            return

        # 5. Проверяем is_generating
        if settings.get("is_generating"):
            logger.info("Scheduler tick: content generation in progress",
                        user_id=user_id)
            return

        # 6. Берём следующий ready пост
        next_ready = await ContentQueueManager.get_next_ready(user_id)
        if not next_ready:
            # Очередь пуста — обработать on_empty
            logger.info("Scheduler tick: queue empty",
                        user_id=user_id, on_empty=on_empty)
            await _handle_empty_queue(bot, user_id, chat_id, on_empty, settings)
            # Обновляем last_processed_at
            await AutoPublishManager.update_last_processed(user_id)
            return

        # 7. Публикация или review
        if moderation == "auto":
            logger.info("Scheduler tick: auto-publishing",
                        user_id=user_id, queue_id=next_ready["id"],
                        action="publish")
            await _publish_queue_item(bot, next_ready, settings)
        else:
            logger.info("Scheduler tick: sending for review",
                        user_id=user_id, queue_id=next_ready["id"],
                        action="review")
            await _send_for_review(bot, next_ready, settings)

        # Обновляем last_processed_at
        await AutoPublishManager.update_last_processed(user_id)

    finally:
        _processing_users.discard(user_id)


async def _handle_empty_queue(bot: Bot, user_id: int, chat_id: int, on_empty: str, settings: dict):
    """Обработка пустой очереди"""
    if on_empty == "pause":
        await AutoPublishManager.set_active(user_id, False)
        try:
            await bot.send_message(
                chat_id,
                "Очередь постов пуста! Авто-публикация приостановлена.\n\n"
                "Сгенерируйте новый контент-план в разделе Авто-публикация."
            )
        except Exception:
            pass
    elif on_empty == "auto_generate":
        await _auto_generate_batch(bot, user_id, settings)


async def _send_for_review(bot: Bot, queue_item: dict, settings: dict):
    """Отправить пост на проверку пользователю"""
    queue_id = queue_item["id"]
    post_id = queue_item.get("post_id")
    chat_id = settings["chat_id"]

    await ContentQueueManager.set_review(queue_id)

    if not post_id:
        return

    post = await PostManager.get_post(post_id)
    if not post:
        return

    text = post.get("final_text") or post.get("generated_text") or ""
    topic = queue_item.get("topic", "")
    scheduled_at = queue_item.get("scheduled_at")

    # Format scheduled time
    date_str = ""
    if scheduled_at:
        tz = ZoneInfo(settings.get("timezone", "Europe/Moscow"))
        msk = scheduled_at.astimezone(tz) if scheduled_at.tzinfo else scheduled_at
        date_str = f"\n📅 Запланировано: {msk.strftime('%d.%m.%Y — %H:%M')} МСК"

    preview = (
        f"👀 Пост готов к проверке!{date_str}\n\n"
        f"{sanitize_html(text)}"
    )

    media_info = post.get("media_info")
    if isinstance(media_info, str):
        media_info = json.loads(media_info)

    kb = review_post_kb(queue_id)

    try:
        if media_info and _has_photo(media_info):
            file_id = _get_first_photo_file_id(media_info)
            if len(preview) <= 1024:
                await bot.send_photo(chat_id, file_id, caption=preview,
                                     reply_markup=kb, parse_mode="HTML")
            else:
                await bot.send_photo(chat_id, file_id)
                await bot.send_message(chat_id, preview, reply_markup=kb, parse_mode="HTML")
        else:
            await bot.send_message(chat_id, preview, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        logger.error("Failed to send review", queue_id=queue_id, error=str(e))


async def _publish_queue_item(bot: Bot, queue_item: dict, settings: dict):
    """Опубликовать пост из очереди в канал"""
    queue_id = queue_item["id"]
    user_id = queue_item["user_id"]
    post_id = queue_item.get("post_id")
    chat_id = settings["chat_id"]
    plan = settings.get("plan", "free")

    if not post_id:
        await ContentQueueManager.update_status(queue_id, "skipped")
        return

    post = await PostManager.get_post(post_id)
    if not post:
        await ContentQueueManager.update_status(queue_id, "skipped")
        return

    channel = await ChannelManager.get_channel(user_id)
    if not channel:
        logger.warning("No channel for auto-publish", user_id=user_id)
        return

    # Check post limit
    limit_info = await UserManager.check_post_limit(chat_id)
    if not limit_info.get("can_post"):
        try:
            await bot.send_message(
                chat_id,
                "Достигнут лимит постов за месяц. Авто-публикация приостановлена.\n"
                "Обновите тариф в разделе Подписка."
            )
        except Exception:
            pass
        await AutoPublishManager.set_active(user_id, False)
        return

    text = post.get("final_text") or post.get("generated_text") or ""
    media_info = post.get("media_info")
    if isinstance(media_info, str):
        media_info = json.loads(media_info)

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

        topic = queue_item.get("topic", "")
        channel_username = channel.get("channel_username", "")
        channel_ref = f"@{channel_username}" if channel_username else "канал"

        try:
            await bot.send_message(
                chat_id,
                f"✅ Авто-публикация: «{topic[:50]}» опубликован в {channel_ref}"
            )
        except Exception:
            pass

        logger.info("Auto-published", queue_id=queue_id, post_id=post_id)
    else:
        error = result.get("error", "Unknown error")
        logger.error("Auto-publish failed", queue_id=queue_id, error=error)
        try:
            await bot.send_message(
                chat_id,
                f"❌ Не удалось автоматически опубликовать пост:\n{error}"
            )
        except Exception:
            pass


async def _send_review_reminders(bot: Bot):
    """Повторная отправка постов на проверку каждые 30 минут, максимум MAX_REVIEW_REMINDERS раз"""
    try:
        review_items = await ContentQueueManager.get_all_review_items()
    except Exception:
        return

    now = datetime.now(timezone.utc)

    for item in review_items:
        reminders_sent = item.get("review_reminders_sent", 0)

        # Автопропуск после MAX_REVIEW_REMINDERS напоминаний
        if reminders_sent >= MAX_REVIEW_REMINDERS:
            chat_id = item.get("chat_id")
            queue_id = item["id"]
            await ContentQueueManager.update_status(queue_id, "skipped")
            logger.info("Auto-skipped review item after max reminders",
                        queue_id=queue_id, reminders_sent=reminders_sent)
            if chat_id:
                try:
                    await bot.send_message(
                        chat_id,
                        "⏭ Пост пропущен (нет ответа). Следующий — по расписанию."
                    )
                except Exception:
                    pass
            continue

        last_reminder = item.get("last_reminder_at")
        if not last_reminder:
            continue

        # Make timezone-aware if needed
        if last_reminder.tzinfo is None:
            last_reminder = last_reminder.replace(tzinfo=timezone.utc)

        elapsed = (now - last_reminder).total_seconds()
        if elapsed < REVIEW_REMINDER_INTERVAL:
            continue

        chat_id = item.get("chat_id")
        queue_id = item["id"]
        post_id = item.get("post_id")

        if not post_id or not chat_id:
            continue

        post = await PostManager.get_post(post_id)
        if not post:
            continue

        text = post.get("final_text") or post.get("generated_text") or ""
        remaining = MAX_REVIEW_REMINDERS - reminders_sent - 1
        skip_warning = ""
        if remaining <= 1:
            skip_warning = "\n\n⚠️ Пост будет пропущен, если не ответить."
        preview = f"🔔 Напоминание: пост ждёт проверки!{skip_warning}\n\n{sanitize_html(text)}"

        kb = review_post_kb(queue_id)

        try:
            media_info = post.get("media_info")
            if isinstance(media_info, str):
                media_info = json.loads(media_info)

            if media_info and _has_photo(media_info):
                file_id = _get_first_photo_file_id(media_info)
                if len(preview) <= 1024:
                    await bot.send_photo(chat_id, file_id, caption=preview,
                                         reply_markup=kb, parse_mode="HTML")
                else:
                    await bot.send_photo(chat_id, file_id)
                    await bot.send_message(chat_id, preview, reply_markup=kb, parse_mode="HTML")
            else:
                await bot.send_message(chat_id, preview, reply_markup=kb, parse_mode="HTML")

            await ContentQueueManager.increment_reminder(queue_id)
            logger.info("Review reminder sent",
                        queue_id=queue_id, reminder_num=reminders_sent + 1)
        except Exception as e:
            logger.error("Review reminder failed", queue_id=queue_id, error=str(e))


async def _auto_generate_batch(bot: Bot, user_id: int, settings: dict):
    """Автоматическая генерация нового контент-плана когда очередь пуста"""
    chat_id = settings["chat_id"]

    # Проверяем флаг is_generating
    if settings.get("is_generating"):
        logger.info("Auto-generate skipped: already generating", user_id=user_id)
        return

    agent = await AgentManager.get_agent(user_id)
    if not agent:
        return

    has_tokens = await UserManager.has_tokens(chat_id)
    if not has_tokens:
        await AutoPublishManager.set_active(user_id, False)
        try:
            await bot.send_message(
                chat_id,
                "Закончились токены для авто-генерации. Авто-публикация приостановлена.\n"
                "Докупите токены в разделе Подписка."
            )
        except Exception:
            pass
        return

    schedule = settings.get("schedule", {})
    generate_covers = settings.get("generate_covers", True)

    # Устанавливаем флаг is_generating
    await AutoPublishManager.set_generating(user_id, True)

    try:
        await generate_content_plan(
            bot=bot,
            chat_id=chat_id,
            user_id=user_id,
            agent_instructions=agent["instructions"],
            agent_model=agent.get("model", "gpt-4o-mini"),
            schedule=schedule,
            generate_covers=generate_covers,
        )

        try:
            await bot.send_message(
                chat_id,
                "🤖 Авто-генерация: новый контент-план создан!\n"
                "Посмотреть в Авто-публикация -> Контент-план"
            )
        except Exception:
            pass

        logger.info("Auto-generate completed", user_id=user_id)
    except Exception as e:
        logger.error("Auto-generate failed", user_id=user_id, error=str(e))
    finally:
        await AutoPublishManager.set_generating(user_id, False)


def _has_photo(media_info: dict) -> bool:
    """Check if media_info contains photos"""
    if not media_info:
        return False
    if media_info.get("type") == "album":
        items = media_info.get("items", [])
        return any(item.get("type") == "photo" for item in items)
    return media_info.get("type") == "photo" and bool(media_info.get("file_id"))


def _get_first_photo_file_id(media_info: dict) -> str:
    """Get file_id of the first photo"""
    if media_info.get("type") == "album":
        for item in media_info.get("items", []):
            if item.get("type") == "photo":
                return item["file_id"]
    if media_info.get("type") == "photo":
        return media_info.get("file_id", "")
    return ""
