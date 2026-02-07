"""
Фоновый планировщик мониторинга каналов-источников.

Каждые CHECK_INTERVAL_SECONDS (300 = 5 минут):
1. Получает все активные watched_channels
2. Для каждого канала парсит t.me/s/{username}
3. Новые посты отправляет пользователю с кнопкой "Рерайт"
4. Обновляет last_checked_post_id
"""

import asyncio
import structlog
from aiogram import Bot

from database.managers.watcher_manager import WatcherManager
from services.channel_watcher import fetch_new_posts, format_post_preview
from bot.keyboards.keyboards import watcher_post_kb

logger = structlog.get_logger()

CHECK_INTERVAL_SECONDS = 300
CHANNEL_DELAY_SECONDS = 3
MAX_NEW_POSTS_PER_CHECK = 3


async def run_watcher(bot: Bot):
    """
    Бесконечный цикл мониторинга каналов.
    Запускается как asyncio.create_task() в app.py lifespan.
    """
    logger.info("Channel watcher started")

    while True:
        try:
            await _check_all_channels(bot)
        except Exception as e:
            logger.error("Watcher error", error=str(e))

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def _check_all_channels(bot: Bot):
    """Проверить все активные отслеживаемые каналы"""
    channels = await WatcherManager.get_all_active_channels()

    if not channels:
        return

    for channel_data in channels:
        try:
            await _check_single_channel(bot, channel_data)
        except Exception as e:
            logger.error("Error checking channel",
                        channel=channel_data.get("channel_username"),
                        error=str(e))

        await asyncio.sleep(CHANNEL_DELAY_SECONDS)


async def _check_single_channel(bot: Bot, channel_data: dict):
    """Проверить один канал и отправить новые посты пользователю"""
    channel_username = channel_data["channel_username"]
    last_post_id = channel_data.get("last_checked_post_id", 0)
    chat_id = channel_data["chat_id"]
    watched_channel_id = channel_data["id"]

    new_posts = await fetch_new_posts(channel_username, after_post_id=last_post_id)

    if not new_posts:
        return

    # Ограничиваем количество (берём самые свежие)
    posts_to_send = new_posts[-MAX_NEW_POSTS_PER_CHECK:]

    for post in posts_to_send:
        already_sent = await WatcherManager.is_post_sent(watched_channel_id, post["post_id"])
        if already_sent:
            continue

        preview_text = format_post_preview(post, channel_username)

        try:
            await bot.send_message(
                chat_id=chat_id,
                text=preview_text,
                parse_mode="HTML",
                reply_markup=watcher_post_kb(watched_channel_id, post["post_id"]),
                disable_web_page_preview=True,
            )

            await WatcherManager.log_sent_post(watched_channel_id, post["post_id"])

            logger.info("Watcher post sent",
                       channel=channel_username,
                       post_id=post["post_id"],
                       chat_id=chat_id)

        except Exception as e:
            logger.error("Failed to send watcher post",
                        chat_id=chat_id,
                        error=str(e))

    # Обновляем last_checked_post_id (максимальный ID из всех новых)
    max_post_id = max(p["post_id"] for p in new_posts)
    await WatcherManager.update_last_checked(watched_channel_id, max_post_id)
