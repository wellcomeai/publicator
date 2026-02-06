"""Хэндлер профиля и статистики"""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from database.managers.user_manager import UserManager
from database.managers.agent_manager import AgentManager
from database.managers.channel_manager import ChannelManager
from database.managers.post_manager import PostManager
from database.managers.settings_manager import UserSettingsManager
from bot.keyboards.keyboards import profile_settings_kb

router = Router()


@router.message(F.text == "👤 Профиль")
async def profile(message: Message, state: FSMContext):
    await state.clear()
    user = await UserManager.get_by_chat_id(message.from_user.id)
    if not user:
        await message.answer("Сначала нажмите /start")
        return

    access = await UserManager.get_access_info(message.from_user.id)

    # Статус доступа — план
    plan_name = access.get("plan_name", "Бесплатный")
    if access.get("subscription_active"):
        status = f"💳 {plan_name} ({access['subscription_days_left']} дн.)"
    else:
        status = f"📋 {plan_name}"

    # Лимит постов
    posts_limit = access.get("posts_limit")
    posts_used = access.get("posts_used", 0)
    if posts_limit:
        posts_info = f"📝 Постов в этом месяце: {posts_used}/{posts_limit}"
    else:
        posts_info = f"📝 Постов в этом месяце: {posts_used} (безлимит)"

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

    # Настройки
    user_settings = await UserSettingsManager.get(user["id"])
    auto_cover = user_settings.get("auto_cover", False)
    cover_status = "ВКЛ" if auto_cover else "ВЫКЛ"

    text = (
        f"👤 <b>Профиль</b>\n\n"
        f"👋 {message.from_user.first_name}\n"
        f"🆔 <code>{message.from_user.id}</code>\n\n"
        f"<b>Статус:</b> {status}\n"
        f"{posts_info}\n"
        f"<b>Агент:</b> {agent_info}\n"
        f"<b>Канал:</b> {channel_info}\n\n"
        f"<b>Токены:</b>\n"
        f"🪙 Баланс: {access['tokens_balance']:,}\n"
        f"📊 Использовано: {access['tokens_used_total']:,}\n\n"
        f"<b>Статистика:</b>\n"
        f"📝 Опубликовано постов: {published}\n"
        f"🔤 Токенов на посты: {total_tokens_used:,}\n\n"
        f"<b>Настройки:</b>\n"
        f"🖼 Авто-обложка: {cover_status}"
    )

    await message.answer(text, parse_mode="HTML", reply_markup=profile_settings_kb(auto_cover))


@router.callback_query(F.data == "toggle_auto_cover")
async def toggle_auto_cover(callback: CallbackQuery, state: FSMContext):
    """Переключить авто-обложку"""
    await callback.answer()

    user = await UserManager.get_by_chat_id(callback.from_user.id)
    if not user:
        await callback.message.answer("Сначала нажмите /start")
        return

    new_value = await UserSettingsManager.toggle_auto_cover(user["id"])
    status = "включена" if new_value else "выключена"

    await callback.message.edit_reply_markup(reply_markup=profile_settings_kb(new_value))
    await callback.answer(f"🖼 Авто-обложка {status}", show_alert=False)
