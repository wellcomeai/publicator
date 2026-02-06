"""Менеджер расписания публикаций"""

import structlog
from typing import Dict, Any, List
from datetime import datetime, timezone
from database.db import get_pool

logger = structlog.get_logger()


class ScheduleManager:

    @staticmethod
    async def schedule_post(
        post_id: int,
        user_id: int,
        channel_id: int,
        publish_at: datetime
    ) -> Dict[str, Any]:
        """Запланировать публикацию"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO scheduled_posts (post_id, user_id, channel_id, publish_at)
                VALUES ($1, $2, $3, $4)
                RETURNING *
            """, post_id, user_id, channel_id, publish_at)
            logger.info("📅 Post scheduled", post_id=post_id, publish_at=publish_at.isoformat())
            return dict(row)

    @staticmethod
    async def get_pending_posts() -> List[Dict[str, Any]]:
        """Получить посты, которые пора публиковать"""
        pool = await get_pool()
        now = datetime.now(timezone.utc)
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT sp.*, p.final_text, p.generated_text, p.media_info,
                       u.chat_id, u.plan
                FROM scheduled_posts sp
                JOIN posts p ON p.id = sp.post_id
                JOIN users u ON u.id = sp.user_id
                WHERE sp.status = 'pending' AND sp.publish_at <= $1
                ORDER BY sp.publish_at ASC
            """, now)
            return [dict(r) for r in rows]

    @staticmethod
    async def mark_published(schedule_id: int):
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE scheduled_posts SET status = 'published', updated_at = NOW()
                WHERE id = $1
            """, schedule_id)

    @staticmethod
    async def mark_failed(schedule_id: int, error: str):
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE scheduled_posts SET status = 'failed', error_message = $2, updated_at = NOW()
                WHERE id = $1
            """, schedule_id, error)

    @staticmethod
    async def cancel_scheduled(schedule_id: int) -> bool:
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE scheduled_posts SET status = 'cancelled', updated_at = NOW()
                WHERE id = $1 AND status = 'pending'
            """, schedule_id)
            return result.split()[-1] != "0"

    @staticmethod
    async def get_user_scheduled(user_id: int) -> List[Dict[str, Any]]:
        """Получить запланированные посты пользователя"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT sp.*, p.generated_text, p.final_text
                FROM scheduled_posts sp
                JOIN posts p ON p.id = sp.post_id
                WHERE sp.user_id = $1 AND sp.status = 'pending'
                ORDER BY sp.publish_at ASC
            """, user_id)
            return [dict(r) for r in rows]
