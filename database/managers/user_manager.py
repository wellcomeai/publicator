"""Менеджер пользователей"""

import structlog
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from database.db import get_pool
from config.settings import config

logger = structlog.get_logger()


class UserManager:

    @staticmethod
    async def get_or_create(chat_id: int, username: str = None, first_name: str = None) -> Dict[str, Any]:
        """Получить или создать пользователя, при создании запустить триал"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            user = await conn.fetchrow("SELECT * FROM users WHERE chat_id = $1", chat_id)
            if user:
                return dict(user)

            now = datetime.now(timezone.utc)
            trial_expires = now + timedelta(days=config.TRIAL_DAYS)

            user = await conn.fetchrow("""
                INSERT INTO users (chat_id, username, first_name, trial_started_at, trial_expires_at, tokens_balance)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING *
            """, chat_id, username, first_name, now, trial_expires, config.DEFAULT_TOKEN_LIMIT)

            logger.info("👤 New user created with trial", chat_id=chat_id, trial_expires=trial_expires.isoformat())
            return dict(user)

    @staticmethod
    async def get_by_chat_id(chat_id: int) -> Optional[Dict[str, Any]]:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE chat_id = $1", chat_id)
            return dict(row) if row else None

    @staticmethod
    async def has_access(chat_id: int) -> bool:
        """Проверить есть ли доступ: активный триал ИЛИ активная подписка"""
        user = await UserManager.get_by_chat_id(chat_id)
        if not user:
            return False

        now = datetime.now(timezone.utc)

        # Триал активен
        if user["trial_expires_at"] and user["trial_expires_at"] > now:
            return True

        # Подписка активна
        if user["is_subscribed"] and user["subscription_expires_at"] and user["subscription_expires_at"] > now:
            return True

        return False

    @staticmethod
    async def has_tokens(chat_id: int) -> bool:
        """Есть ли доступные токены"""
        user = await UserManager.get_by_chat_id(chat_id)
        if not user:
            return False
        return user["tokens_balance"] > 0

    @staticmethod
    async def get_access_info(chat_id: int) -> Dict[str, Any]:
        """Полная информация о доступе пользователя"""
        user = await UserManager.get_by_chat_id(chat_id)
        if not user:
            return {"has_access": False, "reason": "not_found"}

        now = datetime.now(timezone.utc)
        trial_active = bool(user["trial_expires_at"] and user["trial_expires_at"] > now)
        sub_active = bool(user["is_subscribed"] and user["subscription_expires_at"] and user["subscription_expires_at"] > now)

        trial_days_left = 0
        if trial_active:
            trial_days_left = max(0, (user["trial_expires_at"] - now).days)

        sub_days_left = 0
        if sub_active:
            sub_days_left = max(0, (user["subscription_expires_at"] - now).days)

        return {
            "has_access": trial_active or sub_active,
            "trial_active": trial_active,
            "trial_days_left": trial_days_left,
            "subscription_active": sub_active,
            "subscription_days_left": sub_days_left,
            "tokens_balance": user["tokens_balance"],
            "tokens_used_total": user["tokens_used_total"],
        }

    @staticmethod
    async def activate_subscription(chat_id: int, months: int = 1) -> bool:
        """Активировать/продлить подписку"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            user = await conn.fetchrow("SELECT * FROM users WHERE chat_id = $1", chat_id)
            if not user:
                return False

            now = datetime.now(timezone.utc)

            # Если подписка активна — продлеваем от текущей даты окончания
            if user["subscription_expires_at"] and user["subscription_expires_at"] > now:
                new_expires = user["subscription_expires_at"] + timedelta(days=30 * months)
            else:
                new_expires = now + timedelta(days=30 * months)

            await conn.execute("""
                UPDATE users SET is_subscribed = TRUE, subscription_expires_at = $2, updated_at = NOW()
                WHERE chat_id = $1
            """, chat_id, new_expires)

            logger.info("💳 Subscription activated", chat_id=chat_id, expires=new_expires.isoformat())
            return True

    @staticmethod
    async def add_tokens(chat_id: int, amount: int) -> bool:
        """Добавить токены пользователю"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE users SET tokens_balance = tokens_balance + $2, updated_at = NOW()
                WHERE chat_id = $1
            """, chat_id, amount)
            success = result.split()[-1] != "0"
            if success:
                logger.info("🪙 Tokens added", chat_id=chat_id, amount=amount)
            return success

    @staticmethod
    async def spend_tokens(chat_id: int, amount: int) -> bool:
        """Списать токены (проверяет баланс)"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE users 
                SET tokens_balance = tokens_balance - $2, 
                    tokens_used_total = tokens_used_total + $2,
                    updated_at = NOW()
                WHERE chat_id = $1 AND tokens_balance >= $2
            """, chat_id, amount)
            success = result.split()[-1] != "0"
            if not success:
                logger.warning("⚠️ Not enough tokens", chat_id=chat_id, requested=amount)
            return success
