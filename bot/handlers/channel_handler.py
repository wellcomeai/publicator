"""Хэндлер привязки канала"""

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from database.managers.user_manager import UserManager
from database.managers.channel_manager import ChannelManager
from bot.states.states import ChannelLink
from bot.keyboards.keyboards import channel_menu_kb, main_menu_kb, cancel_kb
from services.channel_service import verify_bot_is_admin

router = Router()


@router.message(F.text == "📢 Мой канал")
async def my_channel(message: Message, state: FSMContext):
    await state.clear()
    user = await UserManager.get_by_chat_id(message.from_user.id)
    if not user:
        await message.answer("Сначала нажмите /start")
        return
    
    channel = await ChannelManager.get_channel(user["id"])
    has_channel = bool(channel)
    
    if has_channel:
        ch_name = channel.get("channel_title") or "Без названия"
        ch_username = f"@{channel['channel_username']}" if channel.get("channel_username") else ""
        text = (
            f"📢 <b>Привязанный канал:</b>\n"
            f"{ch_name} {ch_username}\n"
            f"ID: <code>{channel['channel_id']}</code>"
        )
    else:
        text = (
            "📢 Канал не привязан.\n\n"
            "Чтобы привязать канал:\n"
            "1. Добавьте бота администратором в канал\n"
            "2. Дайте права на публикацию\n"
            "3. Перешлите любой пост из канала сюда"
        )
    
    await message.answer(text, reply_markup=channel_menu_kb(has_channel), parse_mode="HTML")


@router.callback_query(F.data == "channel:link")
async def channel_link_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(ChannelLink.waiting_forward)
    await callback.message.answer(
        "📢 Перешлите мне <b>любой пост</b> из канала, который хотите привязать.\n\n"
        "⚠️ Не забудьте добавить бота администратором канала с правом публикации!",
        parse_mode="HTML",
        reply_markup=cancel_kb()
    )


@router.message(ChannelLink.waiting_forward)
async def channel_forward_received(message: Message, state: FSMContext, bot: Bot):
    # Проверяем что это пересланный пост из канала
    if not message.forward_from_chat or message.forward_from_chat.type != "channel":
        await message.answer(
            "❌ Это не пересланный пост из канала.\n"
            "Перешлите мне пост из канала, который хотите привязать."
        )
        return
    
    channel_chat = message.forward_from_chat
    channel_id = channel_chat.id
    channel_title = channel_chat.title
    channel_username = channel_chat.username
    
    # Проверяем права бота в канале
    status_msg = await message.answer("⏳ Проверяю права бота в канале...")
    
    check = await verify_bot_is_admin(bot, channel_id)
    
    if not check["is_admin"]:
        await status_msg.edit_text(
            f"❌ Бот не является администратором канала <b>{channel_title}</b>.\n\n"
            f"Добавьте @{(await bot.get_me()).username} администратором канала и попробуйте снова.",
            parse_mode="HTML"
        )
        return
    
    if not check["can_post"]:
        await status_msg.edit_text(
            f"❌ У бота нет права на публикацию в канале <b>{channel_title}</b>.\n\n"
            f"Дайте боту право «Публикация сообщений» в настройках канала.",
            parse_mode="HTML"
        )
        return
    
    # Привязываем канал
    user = await UserManager.get_by_chat_id(message.from_user.id)
    await ChannelManager.link_channel(
        user_id=user["id"],
        channel_id=channel_id,
        title=channel_title,
        username=channel_username,
    )
    
    await state.clear()

    try:
        await status_msg.delete()
    except Exception:
        pass

    ch_display = f"@{channel_username}" if channel_username else channel_title
    await message.answer(
        f"✅ Канал <b>{ch_display}</b> привязан!\n\n"
        f"Теперь можете создавать и публиковать контент.",
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )


@router.callback_query(F.data == "channel:info")
async def channel_info(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    user = await UserManager.get_by_chat_id(callback.from_user.id)
    channel = await ChannelManager.get_channel(user["id"])
    
    if not channel:
        await callback.message.answer("Канал не привязан.")
        return
    
    check = await verify_bot_is_admin(bot, channel["channel_id"])
    status_emoji = "✅" if check["can_post"] else "❌"
    
    text = (
        f"📢 <b>{channel.get('channel_title', 'Канал')}</b>\n"
        f"{'@' + channel['channel_username'] if channel.get('channel_username') else ''}\n"
        f"ID: <code>{channel['channel_id']}</code>\n\n"
        f"{status_emoji} Права публикации: {'есть' if check['can_post'] else 'нет'}"
    )
    await callback.message.answer(text, parse_mode="HTML")


@router.callback_query(F.data == "channel:unlink")
async def channel_unlink(callback: CallbackQuery):
    await callback.answer()
    user = await UserManager.get_by_chat_id(callback.from_user.id)
    await ChannelManager.unlink_channel(user["id"])
    await callback.message.answer("✅ Канал отвязан.", reply_markup=main_menu_kb())
