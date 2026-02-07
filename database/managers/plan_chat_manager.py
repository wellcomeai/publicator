"""Менеджер чат-сессий для согласования контент-плана"""

import json
import structlog
from typing import Optional, Dict, Any, List
from database.db import get_pool

logger = structlog.get_logger()


class PlanChatManager:
    """CRUD для таблицы plan_chat_sessions"""

    @staticmethod
    async def create_session(user_id: int) -> Dict[str, Any]:
        """
        Создать новую сессию диалога.
        Автоматически отменяет предыдущие активные сессии этого пользователя.
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            # Отменяем старые активные сессии
            await conn.execute(
                """UPDATE plan_chat_sessions
                   SET status = 'cancelled'
                   WHERE user_id = $1 AND status = 'active'""",
                user_id
            )

            row = await conn.fetchrow(
                """INSERT INTO plan_chat_sessions (user_id, messages, status)
                   VALUES ($1, '[]'::jsonb, 'active')
                   RETURNING id, user_id, messages, status, created_at, expires_at""",
                user_id
            )
            logger.info("Plan chat session created", session_id=row["id"], user_id=user_id)
            return dict(row)

    @staticmethod
    async def get_active_session(user_id: int) -> Optional[Dict[str, Any]]:
        """Получить активную сессию пользователя (если есть)"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, user_id, messages, status, created_at, expires_at
                   FROM plan_chat_sessions
                   WHERE user_id = $1 AND status = 'active' AND expires_at > NOW()
                   ORDER BY created_at DESC LIMIT 1""",
                user_id
            )
            return dict(row) if row else None

    @staticmethod
    async def append_message(session_id: int, role: str, content: str) -> None:
        """Добавить сообщение в историю сессии"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            msg = json.dumps({"role": role, "content": content}, ensure_ascii=False)
            await conn.execute(
                """UPDATE plan_chat_sessions
                   SET messages = messages || $1::jsonb
                   WHERE id = $2""",
                f'[{msg}]', session_id
            )

    @staticmethod
    async def get_messages(session_id: int) -> List[Dict[str, str]]:
        """Получить всю историю сообщений сессии"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT messages FROM plan_chat_sessions WHERE id = $1",
                session_id
            )
            if row and row["messages"]:
                return json.loads(row["messages"]) if isinstance(row["messages"], str) else row["messages"]
            return []

    @staticmethod
    async def confirm_session(session_id: int, confirmed_plan: Dict) -> None:
        """Подтвердить план и закрыть сессию"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE plan_chat_sessions
                   SET status = 'confirmed', confirmed_plan = $1::jsonb
                   WHERE id = $2""",
                json.dumps(confirmed_plan, ensure_ascii=False), session_id
            )
            logger.info("Plan chat session confirmed", session_id=session_id)

    @staticmethod
    async def cancel_session(session_id: int) -> None:
        """Отменить сессию"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE plan_chat_sessions
                   SET status = 'cancelled'
                   WHERE id = $1""",
                session_id
            )
            logger.info("Plan chat session cancelled", session_id=session_id)

    @staticmethod
    async def cleanup_expired() -> int:
        """Очистка истёкших сессий. Вызывать из cron/scheduler."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                """UPDATE plan_chat_sessions
                   SET status = 'expired'
                   WHERE status = 'active' AND expires_at < NOW()"""
            )
            count = int(result.split()[-1]) if result else 0
            if count > 0:
                logger.info("Expired plan chat sessions cleaned", count=count)
            return count
