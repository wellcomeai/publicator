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
        """Получить или создать пользователя (freemium: plan='free')"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            user = await conn.fetchrow("SELECT * FROM users WHERE chat_id = $1", chat_id)
            if user:
                return dict(user)

            now = datetime.now(timezone.utc)
            # Первое число следующего месяца
            if now.month == 12:
                next_month = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            else:
                next_month = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)

            user = await conn.fetchrow("""
                INSERT INTO users (chat_id, username, first_name, plan, tokens_balance,
                                   posts_this_month, month_reset_at)
                VALUES ($1, $2, $3, 'free', $4, 0, $5)
                RETURNING *
            """, chat_id, username, first_name, config.DEFAULT_TOKEN_LIMIT, next_month)

            logger.info("👤 New user created (free plan)", chat_id=chat_id)
            return dict(user)

    @staticmethod
    async def get_by_chat_id(chat_id: int) -> Optional[Dict[str, Any]]:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE chat_id = $1", chat_id)
            return dict(row) if row else None

    @staticmethod
    async def has_access(chat_id: int) -> bool:
        """Проверить есть ли доступ: free всегда имеет доступ, платные — по подписке"""
        user = await UserManager.get_by_chat_id(chat_id)
        if not user:
            return False

        plan = user.get("plan", "free")

        # Free — всегда имеет доступ (лимит постов проверяется в check_post_limit)
        if plan == "free":
            return True

        now = datetime.now(timezone.utc)
        # Платный план — проверяем подписку
        if user["subscription_expires_at"] and user["subscription_expires_at"] > now:
            return True

        # Подписка истекла — откатываем на free
        await UserManager._downgrade_to_free(chat_id)
        return True  # free план всё равно имеет доступ

    @staticmethod
    async def has_tokens(chat_id: int) -> bool:
        """Есть ли доступные токены"""
        user = await UserManager.get_by_chat_id(chat_id)
        if not user:
            return False
        return user["tokens_balance"] > 0

    @staticmethod
    async def check_post_limit(chat_id: int) -> Dict[str, Any]:
        """
        Проверка лимита постов для текущего плана.
        Возвращает:
        {
            "can_post": True/False,
            "posts_used": 3,
            "posts_limit": 5,  # None для безлимита
            "plan": "free",
            "watermark": True/False,
        }
        """
        user = await UserManager.get_by_chat_id(chat_id)
        if not user:
            return {"can_post": False, "reason": "not_found"}

        # Сброс счётчика если наступил новый месяц
        await UserManager._maybe_reset_monthly_counter(chat_id)
        # Перечитываем после возможного сброса
        user = await UserManager.get_by_chat_id(chat_id)

        plan_name = user.get("plan", "free")
        plan_config = config.PLANS.get(plan_name, config.PLANS["free"])

        posts_limit = plan_config["posts_per_month"]
        posts_used = user.get("posts_this_month", 0)

        can_post = True
        if posts_limit is not None and posts_used >= posts_limit:
            can_post = False

        return {
            "can_post": can_post,
            "posts_used": posts_used,
            "posts_limit": posts_limit,
            "plan": plan_name,
            "watermark": plan_config.get("watermark", False),
            "allow_video": plan_config.get("allow_video", False),
            "allow_photo": plan_config.get("allow_photo", True),
        }

    @staticmethod
    async def increment_post_count(chat_id: int):
        """Увеличить счётчик постов за месяц"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE users SET posts_this_month = posts_this_month + 1, updated_at = NOW()
                WHERE chat_id = $1
            """, chat_id)

    @staticmethod
    async def _maybe_reset_monthly_counter(chat_id: int):
        """Сброс счётчика если наступил новый месяц"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            user = await conn.fetchrow("SELECT * FROM users WHERE chat_id = $1", chat_id)
            if not user:
                return

            now = datetime.now(timezone.utc)
            reset_at = user.get("month_reset_at")

            if reset_at and now >= reset_at:
                if now.month == 12:
                    next_reset = now.replace(year=now.year + 1, month=1, day=1,
                                             hour=0, minute=0, second=0, microsecond=0)
                else:
                    next_reset = now.replace(month=now.month + 1, day=1,
                                             hour=0, minute=0, second=0, microsecond=0)

                await conn.execute("""
                    UPDATE users SET posts_this_month = 0, month_reset_at = $2, updated_at = NOW()
                    WHERE chat_id = $1
                """, chat_id, next_reset)
                logger.info("🔄 Monthly post counter reset", chat_id=chat_id)

    @staticmethod
    async def _downgrade_to_free(chat_id: int):
        """Откат на free при истечении подписки"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE users SET plan = 'free', is_subscribed = FALSE, updated_at = NOW()
                WHERE chat_id = $1
            """, chat_id)
            logger.info("⬇️ User downgraded to free", chat_id=chat_id)

    @staticmethod
    async def get_access_info(chat_id: int) -> Dict[str, Any]:
        """Полная информация о доступе пользователя"""
        user = await UserManager.get_by_chat_id(chat_id)
        if not user:
            return {"has_access": False, "reason": "not_found"}

        now = datetime.now(timezone.utc)
        plan_name = user.get("plan", "free")
        plan_config = config.PLANS.get(plan_name, config.PLANS["free"])

        sub_active = bool(
            plan_name in ("starter", "pro")
            and user.get("subscription_expires_at")
            and user["subscription_expires_at"] > now
        )

        sub_days_left = 0
        if sub_active and user.get("subscription_expires_at"):
            sub_days_left = max(0, (user["subscription_expires_at"] - now).days)

        # Если подписка истекла — считаем как free
        effective_plan = plan_name if (plan_name == "free" or sub_active) else "free"
        effective_config = config.PLANS.get(effective_plan, config.PLANS["free"])

        posts_limit = effective_config["posts_per_month"]
        posts_used = user.get("posts_this_month", 0)

        return {
            "has_access": True,  # free всегда имеет доступ
            "plan": effective_plan,
            "plan_name": effective_config["name"],
            "subscription_active": sub_active,
            "subscription_days_left": sub_days_left,
            "tokens_balance": user["tokens_balance"],
            "tokens_used_total": user["tokens_used_total"],
            "posts_used": posts_used,
            "posts_limit": posts_limit,  # None для безлимита
            "watermark": effective_config.get("watermark", False),
        }

    @staticmethod
    async def activate_subscription(chat_id: int, plan: str = "pro", months: int = 1) -> bool:
        """Активировать/продлить подписку"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            user = await conn.fetchrow("SELECT * FROM users WHERE chat_id = $1", chat_id)
            if not user:
                return False

            now = datetime.now(timezone.utc)
            duration = timedelta(days=30 * months)

            if user["subscription_expires_at"] and user["subscription_expires_at"] > now:
                new_expires = user["subscription_expires_at"] + duration
            else:
                new_expires = now + duration

            await conn.execute("""
                UPDATE users
                SET plan = $2, is_subscribed = TRUE, subscription_expires_at = $3, updated_at = NOW()
                WHERE chat_id = $1
            """, chat_id, plan, new_expires)

            logger.info("💳 Subscription activated", chat_id=chat_id, plan=plan, expires=new_expires.isoformat())
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
