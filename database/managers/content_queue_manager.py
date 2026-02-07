"""Менеджер очереди контент-плана"""

import json
import structlog
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from database.db import get_pool

logger = structlog.get_logger()


class ContentQueueManager:

    @staticmethod
    async def add_item(
        user_id: int,
        topic: str,
        format: str = None,
        post_id: int = None,
        scheduled_at: datetime = None,
        status: str = "ready",
    ) -> Dict[str, Any]:
        """Добавить элемент в конец очереди"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            max_pos = await conn.fetchval(
                "SELECT COALESCE(MAX(position), 0) FROM content_queue WHERE user_id = $1",
                user_id,
            )
            position = max_pos + 1

            row = await conn.fetchrow("""
                INSERT INTO content_queue (user_id, topic, format, post_id, position, scheduled_at, status)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING *
            """, user_id, topic, format, post_id, position, scheduled_at, status)

            logger.info("📋 Queue item added", user_id=user_id, position=position, topic=topic[:50])
            return dict(row)

    @staticmethod
    async def add_items_batch(user_id: int, items: List[Dict]) -> List[Dict]:
        """Добавить пачку элементов (после генерации плана)"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            max_pos = await conn.fetchval(
                "SELECT COALESCE(MAX(position), 0) FROM content_queue WHERE user_id = $1",
                user_id,
            )

            results = []
            for i, item in enumerate(items):
                position = max_pos + i + 1
                row = await conn.fetchrow("""
                    INSERT INTO content_queue (user_id, topic, format, post_id, position, scheduled_at, status)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    RETURNING *
                """,
                    user_id,
                    item["topic"],
                    item.get("format"),
                    item.get("post_id"),
                    position,
                    item.get("scheduled_at"),
                    item.get("status", "ready"),
                )
                results.append(dict(row))

            logger.info("📋 Batch items added", user_id=user_id, count=len(results))
            return results

    @staticmethod
    async def get_queue(user_id: int, status: str = None) -> List[Dict[str, Any]]:
        """Получить очередь пользователя (опционально фильтр по статусу)"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            if status:
                rows = await conn.fetch("""
                    SELECT * FROM content_queue
                    WHERE user_id = $1 AND status = $2
                    ORDER BY position ASC
                """, user_id, status)
            else:
                rows = await conn.fetch("""
                    SELECT * FROM content_queue
                    WHERE user_id = $1
                    ORDER BY position ASC
                """, user_id)
            return [dict(r) for r in rows]

    @staticmethod
    async def get_queue_count(user_id: int, status: str = None) -> int:
        """Количество элементов в очереди"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            if status:
                return await conn.fetchval(
                    "SELECT COUNT(*) FROM content_queue WHERE user_id = $1 AND status = $2",
                    user_id, status,
                )
            return await conn.fetchval(
                "SELECT COUNT(*) FROM content_queue WHERE user_id = $1",
                user_id,
            )

    @staticmethod
    async def get_active_queue_count(user_id: int) -> int:
        """Количество активных элементов (pending + ready)"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT COUNT(*) FROM content_queue WHERE user_id = $1 AND status IN ('pending', 'ready')",
                user_id,
            )

    @staticmethod
    async def get_item(queue_id: int) -> Optional[Dict[str, Any]]:
        """Получить элемент по ID"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM content_queue WHERE id = $1", queue_id
            )
            return dict(row) if row else None

    @staticmethod
    async def get_item_by_position(user_id: int, position: int) -> Optional[Dict[str, Any]]:
        """Получить элемент по позиции"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM content_queue
                WHERE user_id = $1 AND position = $2 AND status IN ('pending', 'ready')
            """, user_id, position)
            return dict(row) if row else None

    @staticmethod
    async def get_next_ready(user_id: int) -> Optional[Dict[str, Any]]:
        """Получить следующий готовый элемент для публикации"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM content_queue
                WHERE user_id = $1 AND status = 'ready' AND scheduled_at <= NOW()
                ORDER BY position ASC
                LIMIT 1
            """, user_id)
            return dict(row) if row else None

    @staticmethod
    async def update_status(queue_id: int, status: str):
        """Обновить статус"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE content_queue SET status = $2 WHERE id = $1",
                queue_id, status,
            )

    @staticmethod
    async def update_topic(queue_id: int, topic: str, format: str = None):
        """Обновить тему"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            if format:
                await conn.execute(
                    "UPDATE content_queue SET topic = $2, format = $3 WHERE id = $1",
                    queue_id, topic, format,
                )
            else:
                await conn.execute(
                    "UPDATE content_queue SET topic = $2 WHERE id = $1",
                    queue_id, topic,
                )

    @staticmethod
    async def update_post_id(queue_id: int, post_id: int):
        """Привязать сгенерированный пост"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE content_queue SET post_id = $2 WHERE id = $1",
                queue_id, post_id,
            )

    @staticmethod
    async def delete_item(queue_id: int):
        """Удалить элемент"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id FROM content_queue WHERE id = $1", queue_id
            )
            await conn.execute("DELETE FROM content_queue WHERE id = $1", queue_id)
            if row:
                await ContentQueueManager.reorder_after_delete(row["user_id"])
            logger.info("🗑 Queue item deleted", queue_id=queue_id)

    @staticmethod
    async def reorder_after_delete(user_id: int):
        """Пересчитать positions после удаления (1, 2, 3...)"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id FROM content_queue
                WHERE user_id = $1 AND status IN ('pending', 'ready')
                ORDER BY position ASC
            """, user_id)
            for i, row in enumerate(rows, 1):
                await conn.execute(
                    "UPDATE content_queue SET position = $2 WHERE id = $1",
                    row["id"], i,
                )

    @staticmethod
    async def insert_after(user_id: int, after_position: int, topic: str, **kwargs) -> Dict:
        """Вставить элемент после указанной позиции и сдвинуть остальные"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            # Сдвигаем все позиции после after_position
            await conn.execute("""
                UPDATE content_queue
                SET position = position + 1
                WHERE user_id = $1 AND position > $2 AND status IN ('pending', 'ready')
            """, user_id, after_position)

            new_position = after_position + 1
            row = await conn.fetchrow("""
                INSERT INTO content_queue (user_id, topic, format, post_id, position, scheduled_at, status)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING *
            """,
                user_id,
                topic,
                kwargs.get("format"),
                kwargs.get("post_id"),
                new_position,
                kwargs.get("scheduled_at"),
                kwargs.get("status", "ready"),
            )

            logger.info("📋 Queue item inserted", user_id=user_id, position=new_position)
            return dict(row)

    @staticmethod
    async def recalculate_scheduled_at(user_id: int, schedule: dict):
        """Пересчитать scheduled_at для всех active элементов по расписанию"""
        from services.content_plan_service import calculate_schedule_times

        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id FROM content_queue
                WHERE user_id = $1 AND status IN ('pending', 'ready')
                ORDER BY position ASC
            """, user_id)

            if not rows:
                return

            times = calculate_schedule_times(schedule, len(rows))

            for i, row in enumerate(rows):
                scheduled_at = times[i] if i < len(times) else None
                await conn.execute(
                    "UPDATE content_queue SET scheduled_at = $2 WHERE id = $1",
                    row["id"], scheduled_at,
                )

    @staticmethod
    async def get_items_for_review(user_id: int) -> List[Dict]:
        """Элементы в статусе review"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM content_queue WHERE user_id = $1 AND status = 'review'",
                user_id,
            )
            return [dict(r) for r in rows]

    @staticmethod
    async def get_all_review_items() -> List[Dict]:
        """Все элементы в статусе review (для напоминаний)"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT cq.*, u.chat_id
                FROM content_queue cq
                JOIN users u ON u.id = cq.user_id
                WHERE cq.status = 'review'
            """)
            return [dict(r) for r in rows]

    @staticmethod
    async def increment_reminder(queue_id: int):
        """Увеличить счётчик напоминаний"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE content_queue
                SET review_reminders_sent = review_reminders_sent + 1,
                    last_reminder_at = NOW()
                WHERE id = $1
            """, queue_id)

    @staticmethod
    async def set_review(queue_id: int):
        """Установить статус review с фиксацией времени"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE content_queue
                SET status = 'review', last_reminder_at = NOW()
                WHERE id = $1
            """, queue_id)

    @staticmethod
    async def clear_queue(user_id: int):
        """Очистить всю очередь (статусы pending/ready)"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM content_queue WHERE user_id = $1 AND status IN ('pending', 'ready')",
                user_id,
            )
            logger.info("🗑 Queue cleared", user_id=user_id)
