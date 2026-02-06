"""Менеджер каналов"""

import structlog
from typing import Optional, Dict, Any
from database.db import get_pool

logger = structlog.get_logger()


class ChannelManager:

    @staticmethod
    async def link_channel(user_id: int, channel_id: int, title: str = None, username: str = None) -> Dict[str, Any]:
        """Привязать канал (заменяет предыдущий)"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            # Upsert — один канал на юзера
            row = await conn.fetchrow("""
                INSERT INTO channels (user_id, channel_id, channel_title, channel_username)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id) 
                DO UPDATE SET channel_id = $2, channel_title = $3, channel_username = $4, is_active = TRUE
                RETURNING *
            """, user_id, channel_id, title, username)

            logger.info("📢 Channel linked", user_id=user_id, channel_id=channel_id, title=title)
            return dict(row)

    @staticmethod
    async def get_channel(user_id: int) -> Optional[Dict[str, Any]]:
        """Получить привязанный канал"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM channels WHERE user_id = $1 AND is_active = TRUE", user_id
            )
            return dict(row) if row else None

    @staticmethod
    async def unlink_channel(user_id: int) -> bool:
        """Отвязать канал"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM channels WHERE user_id = $1", user_id
            )
            success = result.split()[-1] != "0"
            if success:
                logger.info("🔗 Channel unlinked", user_id=user_id)
            return success
