"""Менеджер настроек авто-публикации"""

import json
import structlog
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from zoneinfo import ZoneInfo
from database.db import get_pool

logger = structlog.get_logger()


class AutoPublishManager:

    @staticmethod
    async def get_settings(user_id: int) -> Optional[Dict[str, Any]]:
        """Получить настройки авто-публикации"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM auto_publish_settings WHERE user_id = $1", user_id
            )
            if row:
                result = dict(row)
                if result.get("schedule") and isinstance(result["schedule"], str):
                    result["schedule"] = json.loads(result["schedule"])
                return result
            return None

    @staticmethod
    async def create_or_update_settings(user_id: int, **kwargs) -> Dict[str, Any]:
        """Создать или обновить настройки (upsert)"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT * FROM auto_publish_settings WHERE user_id = $1", user_id
            )

            if existing:
                set_clauses = []
                values = [user_id]
                idx = 2
                for key, value in kwargs.items():
                    if key == "schedule" and isinstance(value, dict):
                        value = json.dumps(value)
                    set_clauses.append(f"{key} = ${idx}")
                    values.append(value)
                    idx += 1
                set_clauses.append("updated_at = NOW()")

                if set_clauses:
                    query = f"UPDATE auto_publish_settings SET {', '.join(set_clauses)} WHERE user_id = $1 RETURNING *"
                    row = await conn.fetchrow(query, *values)
                else:
                    row = existing
            else:
                schedule = kwargs.get("schedule", {})
                if isinstance(schedule, dict):
                    schedule = json.dumps(schedule)

                row = await conn.fetchrow("""
                    INSERT INTO auto_publish_settings (user_id, schedule, moderation, generate_covers, on_empty, timezone)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING *
                """,
                    user_id,
                    schedule,
                    kwargs.get("moderation", "review"),
                    kwargs.get("generate_covers", True),
                    kwargs.get("on_empty", "pause"),
                    kwargs.get("timezone", "Europe/Moscow"),
                )

            result = dict(row)
            if result.get("schedule") and isinstance(result["schedule"], str):
                result["schedule"] = json.loads(result["schedule"])
            return result

    @staticmethod
    async def update_schedule(user_id: int, schedule: dict) -> Dict[str, Any]:
        """Обновить расписание"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT id FROM auto_publish_settings WHERE user_id = $1", user_id
            )
            schedule_json = json.dumps(schedule)

            if existing:
                row = await conn.fetchrow("""
                    UPDATE auto_publish_settings
                    SET schedule = $2, updated_at = NOW()
                    WHERE user_id = $1
                    RETURNING *
                """, user_id, schedule_json)
            else:
                row = await conn.fetchrow("""
                    INSERT INTO auto_publish_settings (user_id, schedule)
                    VALUES ($1, $2)
                    RETURNING *
                """, user_id, schedule_json)

            result = dict(row)
            if result.get("schedule") and isinstance(result["schedule"], str):
                result["schedule"] = json.loads(result["schedule"])
            logger.info("📅 Schedule updated", user_id=user_id)
            return result

    @staticmethod
    async def toggle_active(user_id: int) -> bool:
        """Переключить is_active, вернуть новое значение"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                UPDATE auto_publish_settings
                SET is_active = NOT is_active, updated_at = NOW()
                WHERE user_id = $1
                RETURNING is_active
            """, user_id)
            if row:
                return row["is_active"]
            return False

    @staticmethod
    async def set_active(user_id: int, active: bool):
        """Установить is_active"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE auto_publish_settings
                SET is_active = $2, updated_at = NOW()
                WHERE user_id = $1
            """, user_id, active)

    @staticmethod
    async def toggle_setting(user_id: int, field: str) -> Any:
        """Toggle настроек: moderation (review/auto), covers (bool), on_empty (pause/auto_generate)"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            current = await conn.fetchrow(
                "SELECT * FROM auto_publish_settings WHERE user_id = $1", user_id
            )
            if not current:
                return None

            if field == "moderation":
                new_val = "auto" if current["moderation"] == "review" else "review"
                await conn.execute("""
                    UPDATE auto_publish_settings SET moderation = $2, updated_at = NOW()
                    WHERE user_id = $1
                """, user_id, new_val)
                return new_val

            elif field == "generate_covers":
                new_val = not current["generate_covers"]
                await conn.execute("""
                    UPDATE auto_publish_settings SET generate_covers = $2, updated_at = NOW()
                    WHERE user_id = $1
                """, user_id, new_val)
                return new_val

            elif field == "on_empty":
                new_val = "auto_generate" if current["on_empty"] == "pause" else "pause"
                await conn.execute("""
                    UPDATE auto_publish_settings SET on_empty = $2, updated_at = NOW()
                    WHERE user_id = $1
                """, user_id, new_val)
                return new_val

            return None

    @staticmethod
    async def update_last_processed(user_id: int):
        """Обновить время последней обработки"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE auto_publish_settings
                SET last_processed_at = NOW()
                WHERE user_id = $1
            """, user_id)

    @staticmethod
    async def set_generating(user_id: int, generating: bool):
        """Установить флаг is_generating"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE auto_publish_settings
                SET is_generating = $2, updated_at = NOW()
                WHERE user_id = $1
            """, user_id, generating)

    @staticmethod
    async def get_active_settings() -> List[Dict[str, Any]]:
        """Все активные настройки (для планировщика)"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT aps.*, u.chat_id, u.plan
                FROM auto_publish_settings aps
                JOIN users u ON u.id = aps.user_id
                WHERE aps.is_active = TRUE
            """)
            results = []
            for row in rows:
                r = dict(row)
                if r.get("schedule") and isinstance(r["schedule"], str):
                    r["schedule"] = json.loads(r["schedule"])
                results.append(r)
            return results

    @staticmethod
    async def get_next_slot_time(user_id: int) -> Optional[datetime]:
        """Рассчитать время следующего слота по расписанию"""
        settings = await AutoPublishManager.get_settings(user_id)
        if not settings or not settings.get("schedule"):
            return None

        schedule = settings["schedule"]
        slots = schedule.get("slots", [])
        if not slots:
            return None

        tz_name = schedule.get("timezone", "Europe/Moscow")
        tz = ZoneInfo(tz_name)
        now_local = datetime.now(timezone.utc).astimezone(tz)

        sorted_slots = sorted(slots, key=lambda s: (s["day"], s["time"]))

        # Check current week first, then next week
        for week_offset in range(2):
            for slot in sorted_slots:
                slot_day = slot["day"]
                h, m = map(int, slot["time"].split(":"))

                current_weekday = now_local.weekday()
                days_ahead = (slot_day - current_weekday) % 7 + (7 * week_offset)
                if days_ahead == 0 and week_offset == 0:
                    # Same day - check time
                    slot_dt = now_local.replace(hour=h, minute=m, second=0, microsecond=0)
                    if slot_dt > now_local:
                        return slot_dt.astimezone(timezone.utc)
                    continue

                slot_date = now_local.date() + timedelta(days=days_ahead)
                slot_dt = datetime(slot_date.year, slot_date.month, slot_date.day, h, m, tzinfo=tz)

                if slot_dt > now_local:
                    return slot_dt.astimezone(timezone.utc)

        return None
