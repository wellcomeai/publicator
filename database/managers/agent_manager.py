"""Менеджер ИИ-агентов"""

import structlog
from typing import Optional, Dict, Any
from database.db import get_pool

logger = structlog.get_logger()


class AgentManager:

    @staticmethod
    async def create_or_update(user_id: int, agent_name: str, instructions: str, model: str = "gpt-4o-mini") -> Dict[str, Any]:
        """Создать или обновить агента (один на пользователя)"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO agents (user_id, agent_name, instructions, model)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id) 
                DO UPDATE SET agent_name = $2, instructions = $3, model = $4, updated_at = NOW()
                RETURNING *
            """, user_id, agent_name, instructions, model)

            logger.info("🤖 Agent created/updated", user_id=user_id, name=agent_name)
            return dict(row)

    @staticmethod
    async def get_agent(user_id: int) -> Optional[Dict[str, Any]]:
        """Получить агента пользователя"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM agents WHERE user_id = $1 AND is_active = TRUE", user_id
            )
            return dict(row) if row else None

    @staticmethod
    async def delete_agent(user_id: int) -> bool:
        """Удалить агента"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("DELETE FROM agents WHERE user_id = $1", user_id)
            success = result.split()[-1] != "0"
            if success:
                logger.info("🗑️ Agent deleted", user_id=user_id)
            return success

    @staticmethod
    async def has_agent(user_id: int) -> bool:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM agents WHERE user_id = $1 AND is_active = TRUE)", user_id
            )
            return row
