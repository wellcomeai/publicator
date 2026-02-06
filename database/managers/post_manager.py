"""Менеджер постов"""

import json
import structlog
from typing import Optional, Dict, Any, List
from database.db import get_pool

logger = structlog.get_logger()


class PostManager:

    @staticmethod
    async def create_post(
        user_id: int,
        generated_text: str,
        original_text: str = None,
        media_info: dict = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        conversation_history: list = None
    ) -> Dict[str, Any]:
        """Создать новый пост (draft)"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO posts (user_id, original_text, generated_text, final_text, 
                                   media_info, input_tokens, output_tokens, conversation_history)
                VALUES ($1, $2, $3, $3, $4, $5, $6, $7)
                RETURNING *
            """,
                user_id,
                original_text,
                generated_text,
                json.dumps(media_info) if media_info else None,
                input_tokens,
                output_tokens,
                json.dumps(conversation_history or [])
            )

            logger.info("📝 Post created", user_id=user_id, post_id=row["id"])
            return dict(row)

    @staticmethod
    async def get_post(post_id: int) -> Optional[Dict[str, Any]]:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM posts WHERE id = $1", post_id)
            if row:
                result = dict(row)
                # Parse JSON fields
                if result.get("media_info") and isinstance(result["media_info"], str):
                    result["media_info"] = json.loads(result["media_info"])
                if result.get("conversation_history") and isinstance(result["conversation_history"], str):
                    result["conversation_history"] = json.loads(result["conversation_history"])
                return result
            return None

    @staticmethod
    async def get_user_draft(user_id: int) -> Optional[Dict[str, Any]]:
        """Получить текущий черновик пользователя"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM posts 
                WHERE user_id = $1 AND status IN ('draft', 'editing')
                ORDER BY created_at DESC LIMIT 1
            """, user_id)
            if row:
                result = dict(row)
                if result.get("media_info") and isinstance(result["media_info"], str):
                    result["media_info"] = json.loads(result["media_info"])
                if result.get("conversation_history") and isinstance(result["conversation_history"], str):
                    result["conversation_history"] = json.loads(result["conversation_history"])
                return result
            return None

    @staticmethod
    async def update_post_text(
        post_id: int,
        new_text: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        conversation_history: list = None
    ) -> bool:
        """Обновить текст поста (при редактировании)"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE posts 
                SET final_text = $2, 
                    input_tokens = input_tokens + $3, 
                    output_tokens = output_tokens + $4,
                    conversation_history = $5,
                    status = 'editing',
                    updated_at = NOW()
                WHERE id = $1
            """,
                post_id,
                new_text,
                input_tokens,
                output_tokens,
                json.dumps(conversation_history) if conversation_history else '[]'
            )
            return result.split()[-1] != "0"

    @staticmethod
    async def mark_published(post_id: int, channel_id: int) -> bool:
        """Отметить пост как опубликованный"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE posts 
                SET status = 'published', channel_id = $2, published_at = NOW(), updated_at = NOW()
                WHERE id = $1
            """, post_id, channel_id)
            success = result.split()[-1] != "0"
            if success:
                logger.info("📢 Post published", post_id=post_id, channel_id=channel_id)
            return success

    @staticmethod
    async def discard_draft(post_id: int) -> bool:
        """Удалить черновик"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM posts WHERE id = $1 AND status IN ('draft', 'editing')", post_id
            )
            return result.split()[-1] != "0"

    @staticmethod
    async def update_media_info(post_id: int, media_info: Optional[Dict]) -> bool:
        """Обновить media_info поста"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE posts SET media_info = $2, updated_at = NOW()
                WHERE id = $1
            """, post_id, json.dumps(media_info) if media_info else None)
            return result.split()[-1] != "0"

    @staticmethod
    async def update_post_status(post_id: int, status: str) -> bool:
        """Обновить статус поста"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE posts SET status = $2, updated_at = NOW()
                WHERE id = $1
            """, post_id, status)
            return result.split()[-1] != "0"

    @staticmethod
    async def get_user_stats(user_id: int) -> Dict[str, Any]:
        """Статистика постов пользователя"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            stats = await conn.fetchrow("""
                SELECT 
                    COUNT(*) FILTER (WHERE status = 'published') AS published_count,
                    COUNT(*) AS total_count,
                    COALESCE(SUM(input_tokens), 0) AS total_input_tokens,
                    COALESCE(SUM(output_tokens), 0) AS total_output_tokens
                FROM posts WHERE user_id = $1
            """, user_id)
            return dict(stats) if stats else {}
