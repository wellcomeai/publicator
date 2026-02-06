"""Менеджер пользовательских настроек"""

import structlog
from typing import Dict, Any
from database.db import get_pool

logger = structlog.get_logger()


class UserSettingsManager:

    @staticmethod
    async def get(user_id: int) -> Dict[str, Any]:
        """Получить настройки (создать дефолтные если нет)"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM user_settings WHERE user_id = $1", user_id
            )
            if row:
                return dict(row)

            # Создаём дефолтные настройки
            row = await conn.fetchrow("""
                INSERT INTO user_settings (user_id)
                VALUES ($1)
                ON CONFLICT (user_id) DO NOTHING
                RETURNING *
            """, user_id)

            if row:
                return dict(row)

            # На случай гонки — повторный SELECT
            row = await conn.fetchrow(
                "SELECT * FROM user_settings WHERE user_id = $1", user_id
            )
            return dict(row) if row else {"user_id": user_id, "auto_cover": False, "default_image_style": ""}

    @staticmethod
    async def toggle_auto_cover(user_id: int) -> bool:
        """Переключить авто-обложку, вернуть новое значение"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            # Убедимся что запись существует
            await conn.execute("""
                INSERT INTO user_settings (user_id)
                VALUES ($1)
                ON CONFLICT (user_id) DO NOTHING
            """, user_id)

            row = await conn.fetchrow("""
                UPDATE user_settings
                SET auto_cover = NOT auto_cover, updated_at = NOW()
                WHERE user_id = $1
                RETURNING auto_cover
            """, user_id)

            new_value = row["auto_cover"] if row else False
            logger.info("Settings toggled", user_id=user_id, auto_cover=new_value)
            return new_value

    @staticmethod
    async def update(user_id: int, **kwargs) -> Dict[str, Any]:
        """Обновить произвольные настройки"""
        allowed = {"auto_cover", "default_image_style"}
        filtered = {k: v for k, v in kwargs.items() if k in allowed}
        if not filtered:
            return await UserSettingsManager.get(user_id)

        pool = await get_pool()
        async with pool.acquire() as conn:
            # Убедимся что запись существует
            await conn.execute("""
                INSERT INTO user_settings (user_id)
                VALUES ($1)
                ON CONFLICT (user_id) DO NOTHING
            """, user_id)

            set_clauses = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(filtered))
            values = [user_id] + list(filtered.values())

            await conn.execute(f"""
                UPDATE user_settings
                SET {set_clauses}, updated_at = NOW()
                WHERE user_id = $1
            """, *values)

            return await UserSettingsManager.get(user_id)
