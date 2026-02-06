"""Фоновый планировщик публикаций"""

import json
import asyncio
import structlog
from datetime import datetime, timezone
from aiogram import Bot

from database.managers.schedule_manager import ScheduleManager
from database.managers.post_manager import PostManager
from database.managers.user_manager import UserManager
from services.channel_service import publish_post
from config.settings import config

logger = structlog.get_logger()

CHECK_INTERVAL_SECONDS = 60


async def run_scheduler(bot: Bot):
    """
    Бесконечный цикл: каждую минуту проверяет scheduled_posts
    и публикует те, у которых publish_at <= now.
    """
    logger.info("📅 Scheduler started")

    while True:
        try:
            await _process_scheduled_posts(bot)
        except Exception as e:
            logger.error("❌ Scheduler error", error=str(e))

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def _process_scheduled_posts(bot: Bot):
    """Обработка запланированных постов"""
    pending = await ScheduleManager.get_pending_posts()

    if not pending:
        return

    logger.info(f"📅 Processing {len(pending)} scheduled posts")

    for item in pending:
        schedule_id = item["id"]
        post_id = item["post_id"]
        channel_id = item["channel_id"]
        chat_id = item["chat_id"]
        plan = item.get("plan", "free")

        text = item.get("final_text") or item.get("generated_text") or ""
        media_info = item.get("media_info")
        if isinstance(media_info, str):
            media_info = json.loads(media_info)

        # Водяной знак для free плана
        watermark = (plan == "free")

        try:
            result = await publish_post(
                bot=bot,
                channel_id=channel_id,
                text=text,
                media_info=media_info,
                watermark=watermark,
            )

            if result["success"]:
                await ScheduleManager.mark_published(schedule_id)
                await PostManager.mark_published(post_id, channel_id)
                await UserManager.increment_post_count(chat_id)

                # Уведомляем пользователя
                try:
                    preview = text[:100] + "..." if len(text) > 100 else text
                    await bot.send_message(
                        chat_id,
                        f"✅ Запланированный пост опубликован!\n\n"
                        f"<i>{preview}</i>",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

                logger.info("✅ Scheduled post published",
                           schedule_id=schedule_id, post_id=post_id)
            else:
                error = result.get("error", "Unknown error")
                await ScheduleManager.mark_failed(schedule_id, error)

                try:
                    await bot.send_message(
                        chat_id,
                        f"❌ Не удалось опубликовать запланированный пост:\n{error}"
                    )
                except Exception:
                    pass

                logger.error("❌ Scheduled post failed",
                           schedule_id=schedule_id, error=error)

        except Exception as e:
            await ScheduleManager.mark_failed(schedule_id, str(e))
            logger.error("❌ Scheduled post exception",
                       schedule_id=schedule_id, error=str(e))
