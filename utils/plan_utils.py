"""Утилиты тарифных планов"""

from config.settings import config


def plan_allows_schedule(plan: str) -> bool:
    plan_config = config.PLANS.get(plan, config.PLANS["free"])
    return plan_config.get("allow_schedule", False)
