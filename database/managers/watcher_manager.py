"""Менеджер отслеживаемых каналов"""

import structlog
from typing import Dict, Any, List
from database.db import get_pool

logger = structlog.get_logger()


class WatcherManager:

    @staticmethod
    async def add_channel(user_id: int, channel_username: str, channel_title: str = None) -> Dict[str, Any]:
        """
        Добавить канал для отслеживания.
        channel_username — без @, например "durov".
        Возвращает запись или dict с error если дубликат.
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO watched_channels (user_id, channel_username, channel_title)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id, channel_username) DO NOTHING
                RETURNING *
            """, user_id, channel_username.lower(), channel_title)

            if not row:
                return {"error": True, "message": "Этот канал уже добавлен"}

            logger.info("Watched channel added", user_id=user_id, channel=channel_username)
            return dict(row)

    @staticmethod
    async def remove_channel(watched_channel_id: int, user_id: int) -> bool:
        """Удалить отслеживаемый канал (проверяем принадлежность)"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM watched_channels WHERE id = $1 AND user_id = $2",
                watched_channel_id, user_id
            )
            success = result.split()[-1] != "0"
            if success:
                logger.info("Watched channel removed", id=watched_channel_id)
            return success

    @staticmethod
    async def get_user_channels(user_id: int) -> List[Dict[str, Any]]:
        """Получить все отслеживаемые каналы пользователя"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM watched_channels
                WHERE user_id = $1 AND is_active = TRUE
                ORDER BY created_at ASC
            """, user_id)
            return [dict(r) for r in rows]

    @staticmethod
    async def count_user_channels(user_id: int) -> int:
        """Количество отслеживаемых каналов у пользователя"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT COUNT(*) FROM watched_channels WHERE user_id = $1 AND is_active = TRUE",
                user_id
            )

    @staticmethod
    async def get_all_active_channels() -> List[Dict[str, Any]]:
        """Получить ВСЕ активные отслеживаемые каналы (для фонового scheduler)"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT wc.*, u.chat_id, u.plan
                FROM watched_channels wc
                JOIN users u ON u.id = wc.user_id
                WHERE wc.is_active = TRUE
            """)
            return [dict(r) for r in rows]

    @staticmethod
    async def update_last_checked(watched_channel_id: int, last_post_id: int):
        """Обновить ID последнего проверенного поста"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE watched_channels
                SET last_checked_post_id = $2, last_checked_at = NOW()
                WHERE id = $1
            """, watched_channel_id, last_post_id)

    @staticmethod
    async def is_post_sent(watched_channel_id: int, post_id: int) -> bool:
        """Проверить, отправляли ли уже этот пост пользователю"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval("""
                SELECT EXISTS(
                    SELECT 1 FROM watched_posts_log
                    WHERE watched_channel_id = $1 AND post_id = $2
                )
            """, watched_channel_id, post_id)

    @staticmethod
    async def log_sent_post(watched_channel_id: int, post_id: int):
        """Записать что пост отправлен пользователю"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO watched_posts_log (watched_channel_id, post_id)
                VALUES ($1, $2)
                ON CONFLICT (watched_channel_id, post_id) DO NOTHING
            """, watched_channel_id, post_id)

    @staticmethod
    async def mark_rewritten(watched_channel_id: int, post_id: int):
        """Отметить что пост был переписан"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE watched_posts_log SET was_rewritten = TRUE
                WHERE watched_channel_id = $1 AND post_id = $2
            """, watched_channel_id, post_id)
