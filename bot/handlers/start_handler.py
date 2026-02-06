"""Хэндлер /start и главное меню"""

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext

from database.managers.user_manager import UserManager
from bot.keyboards.keyboards import main_menu_kb

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
    
    access = await UserManager.get_access_info(message.from_user.id)
    
    if access["subscription_active"]:
        access_text = f"💳 Подписка активна: {access['subscription_days_left']} дн."
    elif access["trial_active"]:
        access_text = f"🎁 Пробный период: {access['trial_days_left']} дн."
    else:
        access_text = "⚠️ Нет активной подписки"
    
    text = (
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        f"Я — <b>Публикатор ИИ</b> 🤖\n"
        f"Помогу создавать и публиковать контент в твой Telegram-канал с помощью ИИ.\n\n"
        f"<b>Как начать:</b>\n"
        f"1️⃣ Создай ИИ-агента — опиши стиль и тему контента\n"
        f"2️⃣ Привяжи канал — перешли мне любой пост из канала\n"
        f"3️⃣ Создавай контент — пиши что хочешь опубликовать\n\n"
        f"{access_text}\n"
        f"🪙 Токены: {access['tokens_balance']:,}"
    )
    
    await message.answer(text, reply_markup=main_menu_kb(), parse_mode="HTML")
