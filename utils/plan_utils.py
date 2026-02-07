"""Утилиты тарифных планов"""

from config.settings import config


def plan_allows_schedule(plan: str) -> bool:
    plan_config = config.PLANS.get(plan, config.PLANS["free"])
    return plan_config.get("allow_schedule", False)


def plan_allows_auto_publish(plan: str) -> bool:
    return plan in ("starter", "pro")


AUTO_PUBLISH_LIMITS = {
    "free": {
        "allowed": False,
    },
    "starter": {
        "allowed": True,
        "max_slots_per_day": 1,
        "max_queue_size": 10,
        "moderation_only_review": True,
        "allow_ai_plan": False,
    },
    "pro": {
        "allowed": True,
        "max_slots_per_day": 5,
        "max_queue_size": 50,
        "moderation_only_review": False,
        "allow_ai_plan": True,
    },
}


def get_auto_publish_limits(plan: str) -> dict:
    return AUTO_PUBLISH_LIMITS.get(plan, AUTO_PUBLISH_LIMITS["free"])


async def get_menu_flags(chat_id: int) -> dict:
    """Получить флаги для main_menu_kb на основе плана"""
    from database.managers.user_manager import UserManager
    user = await UserManager.get_by_chat_id(chat_id)
    plan = user.get("plan", "free") if user else "free"
    return {
        "show_schedule": plan_allows_schedule(plan),
        "show_auto_publish": plan_allows_auto_publish(plan),
    }
