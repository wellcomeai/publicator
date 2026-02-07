"""Хэндлер /start и главное меню"""

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext

from database.managers.user_manager import UserManager
from database.managers.agent_manager import AgentManager
from bot.keyboards.keyboards import main_menu_kb
from utils.plan_utils import plan_allows_schedule

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Регистрация и приветствие"""
    await state.clear()

    user = await UserManager.get_or_create(
        chat_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )

    # Проверяем — есть ли агент. Если нет — онбординг.
    has_agent = await AgentManager.has_agent(user["id"])

    if not has_agent:
        from bot.handlers.onboarding_handler import start_onboarding
        await start_onboarding(message, state, user)
        return

    # Обычное приветствие для существующих пользователей
    access = await UserManager.get_access_info(message.from_user.id)
    plan_name = access.get("plan_name", "Бесплатный")

    if access.get("subscription_active"):
        access_text = f"💳 {plan_name} — {access['subscription_days_left']} дн."
    else:
        posts_limit = access.get("posts_limit", 5)
        posts_used = access.get("posts_used", 0)
        if posts_limit:
            access_text = f"📋 {plan_name} — {posts_used}/{posts_limit} постов"
        else:
            access_text = f"📋 {plan_name} — безлимит"

    text = (
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        f"Я — <b>Публикатор ИИ</b> 🤖\n\n"
        f"Создаю посты, рерайчу чужой контент, генерирую AI-обложки "
        f"и публикую всё в твой Telegram-канал — в один клик.\n\n"
        f"{access_text}\n"
        f"🪙 Токены: {access['tokens_balance']:,}"
    )

    plan = access.get("plan", "free")
    show_schedule = plan_allows_schedule(plan)
    await message.answer(text, reply_markup=main_menu_kb(show_schedule=show_schedule), parse_mode="HTML")
