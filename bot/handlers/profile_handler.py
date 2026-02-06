"""Хэндлер профиля и статистики"""

from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from database.managers.user_manager import UserManager
from database.managers.agent_manager import AgentManager
from database.managers.channel_manager import ChannelManager
from database.managers.post_manager import PostManager

router = Router()


@router.message(F.text == "👤 Профиль")
async def profile(message: Message, state: FSMContext):
    await state.clear()
    user = await UserManager.get_by_chat_id(message.from_user.id)
    if not user:
        await message.answer("Сначала нажмите /start")
        return
    
    access = await UserManager.get_access_info(message.from_user.id)
    
    # Статус доступа
    if access["trial_active"]:
        status = f"🎁 Пробный период ({access['trial_days_left']} дн.)"
    elif access["subscription_active"]:
        status = f"💳 Подписка активна ({access['subscription_days_left']} дн.)"
    else:
        status = "❌ Нет активной подписки"
    
    # Агент
    agent = await AgentManager.get_agent(user["id"])
    agent_info = f"🤖 {agent['agent_name']}" if agent else "🤖 Не создан"
    
    # Канал
    channel = await ChannelManager.get_channel(user["id"])
    if channel:
        ch_display = f"@{channel['channel_username']}" if channel.get("channel_username") else channel.get("channel_title", "—")
        channel_info = f"📢 {ch_display}"
    else:
        channel_info = "📢 Не привязан"
    
    # Статистика
    stats = await PostManager.get_user_stats(user["id"])
    published = stats.get("published_count", 0)
    total_tokens_used = stats.get("total_input_tokens", 0) + stats.get("total_output_tokens", 0)
    
    text = (
        f"👤 <b>Профиль</b>\n\n"
        f"👋 {message.from_user.first_name}\n"
        f"🆔 <code>{message.from_user.id}</code>\n\n"
        f"<b>Статус:</b> {status}\n"
        f"<b>Агент:</b> {agent_info}\n"
        f"<b>Канал:</b> {channel_info}\n\n"
        f"<b>Токены:</b>\n"
        f"🪙 Баланс: {access['tokens_balance']:,}\n"
        f"📊 Использовано: {access['tokens_used_total']:,}\n\n"
        f"<b>Статистика:</b>\n"
        f"📝 Опубликовано постов: {published}\n"
        f"🔤 Токенов на посты: {total_tokens_used:,}"
    )
    
    await message.answer(text, parse_mode="HTML")
