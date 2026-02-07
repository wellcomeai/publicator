"""Утилиты тарифных планов"""

from config.settings import config


def plan_allows_schedule(plan: str) -> bool:
    plan_config = config.PLANS.get(plan, config.PLANS["free"])
    return plan_config.get("allow_schedule", False)


async def get_menu_flags(chat_id: int) -> dict:
    """Получить флаги для main_menu_kb на основе плана"""
    from database.managers.user_manager import UserManager
    user = await UserManager.get_by_chat_id(chat_id)
    plan = user.get("plan", "free") if user else "free"
    return {
        "show_schedule": plan_allows_schedule(plan),
    }
