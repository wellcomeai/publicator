"""Онбординг-визард для новых пользователей"""

import structlog
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from database.managers.user_manager import UserManager
from database.managers.agent_manager import AgentManager
from database.managers.channel_manager import ChannelManager
from bot.states.states import Onboarding, ContentGeneration
from bot.keyboards.keyboards import (
    preset_choice_kb, onboarding_channel_kb,
    onboarding_first_post_kb, main_menu_kb, cancel_kb
)
from utils.plan_utils import get_menu_flags
from config.presets import AGENT_PRESETS
from services.channel_service import verify_bot_is_admin

logger = structlog.get_logger()
router = Router()


async def start_onboarding(message: Message, state: FSMContext, user: dict):
    """Точка входа в онбординг — вызывается из start_handler"""
    await state.clear()
    await state.set_state(Onboarding.choosing_preset)

    text = (
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        f"Я — <b>Публикатор ИИ</b> 🤖\n"
        f"Помогу создавать контент для твоего Telegram-канала.\n\n"
        f"Давай настроим всё за 2 минуты!\n\n"
        f"<b>Шаг 1 из 3:</b> Выберите тип вашего канала 👇"
    )

    await message.answer(text, reply_markup=preset_choice_kb(), parse_mode="HTML")


# ===== ШАГ 1: ВЫБОР ПРЕСЕТА =====

@router.callback_query(Onboarding.choosing_preset, F.data.startswith("preset:"))
async def preset_chosen(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    preset_key = callback.data.split(":")[1]

    if preset_key == "custom":
        await state.set_state(Onboarding.custom_prompt)
        await callback.message.answer(
            "✏️ Опишите ваш канал и стиль контента.\n\n"
            "<i>Например: «Канал про криптовалюты для трейдеров. "
            "Стиль дружеский но экспертный. Эмодзи умеренно.»</i>",
            parse_mode="HTML",
            reply_markup=cancel_kb()
        )
        return

    preset = AGENT_PRESETS.get(preset_key)
    if not preset:
        await callback.message.answer("❌ Неизвестный пресет. Попробуйте ещё раз.")
        return

    await state.update_data(
        agent_instructions=preset["instructions"],
        agent_name=preset["default_agent_name"],
        preset_key=preset_key,
    )
    await state.set_state(Onboarding.naming_agent)

    await callback.message.answer(
        f"✅ Отлично! Тип: <b>{preset['emoji']} {preset['name']}</b>\n\n"
        f"<b>Шаг 2 из 3:</b> Как назвать вашего ИИ-агента?\n\n"
        f"Предлагаю: <b>{preset['default_agent_name']}</b>\n"
        f"Отправьте своё название или нажмите кнопку ниже 👇",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"✅ {preset['default_agent_name']}",
                callback_data="onboard:use_default_name"
            )],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
        ])
    )


# ===== КАСТОМНЫЙ ПРОМТ =====

@router.message(Onboarding.custom_prompt, F.text)
async def custom_prompt_received(message: Message, state: FSMContext):
    instructions = message.text.strip()
    if len(instructions) < 10:
        await message.answer("❌ Слишком коротко (минимум 10 символов). Попробуйте ещё раз:")
        return
    if len(instructions) > 2000:
        await message.answer(f"❌ Слишком длинно ({len(instructions)}/2000). Сократите:")
        return

    await state.update_data(
        agent_instructions=instructions,
        agent_name="Мой агент",
        preset_key="custom",
    )
    await state.set_state(Onboarding.naming_agent)

    await message.answer(
        f"✅ Промт сохранён!\n\n"
        f"<b>Шаг 2 из 3:</b> Как назвать агента?\n\n"
        f"Введите название (например: «Крипто-эксперт», «Кулинарный блог»):",
        parse_mode="HTML"
    )


# ===== ШАГ 2: ИМЯ АГЕНТА =====

@router.callback_query(Onboarding.naming_agent, F.data == "onboard:use_default_name")
async def use_default_name(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    agent_name = data.get("agent_name", "Мой агент")

    user = await UserManager.get_by_chat_id(callback.from_user.id)
    await AgentManager.create_or_update(
        user_id=user["id"],
        agent_name=agent_name,
        instructions=data["agent_instructions"],
    )

    await _ask_channel(callback.message, state)


@router.message(Onboarding.naming_agent, F.text)
async def custom_name_received(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2 or len(name) > 100:
        await message.answer("❌ Название: от 2 до 100 символов. Попробуйте ещё раз:")
        return

    data = await state.get_data()

    user = await UserManager.get_by_chat_id(message.from_user.id)
    await AgentManager.create_or_update(
        user_id=user["id"],
        agent_name=name,
        instructions=data["agent_instructions"],
    )

    await _ask_channel(message, state)


async def _ask_channel(message_or_answer, state: FSMContext):
    """Переход к шагу 3: привязка канала"""
    await state.set_state(Onboarding.waiting_channel)

    text = (
        "✅ Агент создан!\n\n"
        "<b>Шаг 3 из 3:</b> Привяжите ваш канал.\n\n"
        "1. Добавьте бота администратором в канал\n"
        "2. Дайте право на публикацию\n"
        "3. Перешлите мне <b>любой пост</b> из канала\n\n"
        "Или нажмите «Пропустить» — привяжете позже."
    )

    await message_or_answer.answer(
        text,
        parse_mode="HTML",
        reply_markup=onboarding_channel_kb()
    )


# ===== ШАГ 3: ПРИВЯЗКА КАНАЛА =====

@router.callback_query(Onboarding.waiting_channel, F.data == "onboard:skip_channel")
async def skip_channel(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await _finish_onboarding(callback.message, state, callback.from_user.id, channel_linked=False)


@router.message(Onboarding.waiting_channel)
async def onboarding_channel_forward(message: Message, state: FSMContext, bot: Bot):
    """Обработка пересланного поста из канала"""
    if not message.forward_from_chat or message.forward_from_chat.type != "channel":
        await message.answer(
            "❌ Это не пост из канала.\n"
            "Перешлите любой пост из вашего канала, или нажмите «Пропустить».",
            reply_markup=onboarding_channel_kb()
        )
        return

    channel_chat = message.forward_from_chat
    channel_id = channel_chat.id
    channel_title = channel_chat.title
    channel_username = channel_chat.username

    status_msg = await message.answer("⏳ Проверяю права бота...")

    check = await verify_bot_is_admin(bot, channel_id)

    if not check["is_admin"]:
        bot_info = await bot.get_me()
        await status_msg.edit_text(
            f"❌ Бот не администратор канала <b>{channel_title}</b>.\n\n"
            f"Добавьте @{bot_info.username} администратором и попробуйте снова.",
            parse_mode="HTML"
        )
        return

    if not check["can_post"]:
        await status_msg.edit_text(
            f"❌ Нет права на публикацию в <b>{channel_title}</b>.\n"
            f"Дайте боту право «Публикация сообщений».",
            parse_mode="HTML"
        )
        return

    user = await UserManager.get_by_chat_id(message.from_user.id)
    await ChannelManager.link_channel(
        user_id=user["id"],
        channel_id=channel_id,
        title=channel_title,
        username=channel_username,
    )

    try:
        await status_msg.delete()
    except Exception:
        pass

    await _finish_onboarding(message, state, message.from_user.id, channel_linked=True)


# ===== ЗАВЕРШЕНИЕ ОНБОРДИНГА =====

async def _finish_onboarding(message, state: FSMContext, chat_id: int, channel_linked: bool):
    """Завершение онбординга — предложение создать первый пост"""
    await state.clear()

    access = await UserManager.get_access_info(chat_id)
    posts_limit = access.get("posts_limit", 5)

    if channel_linked:
        text = (
            "🎉 <b>Настройка завершена!</b>\n\n"
            "✅ Агент создан\n"
            "✅ Канал привязан\n\n"
            f"У вас {posts_limit} бесплатных постов в месяц.\n"
            f"Хотите создать первый пост прямо сейчас? 👇"
        )
    else:
        text = (
            "🎉 <b>Почти готово!</b>\n\n"
            "✅ Агент создан\n"
            "⏳ Канал — привяжете позже (📢 Мой канал)\n\n"
            f"У вас {posts_limit} бесплатных постов в месяц.\n"
            f"Хотите попробовать создать пост? 👇"
        )

    await message.answer(text, reply_markup=onboarding_first_post_kb(), parse_mode="HTML")


@router.callback_query(F.data == "onboard:first_post")
async def onboarding_first_post(callback: CallbackQuery, state: FSMContext):
    """Перенаправление в создание поста из онбординга"""
    await callback.answer()
    await state.set_state(ContentGeneration.waiting_prompt)
    await callback.message.answer(
        "✍️ Опишите, какой пост хотите создать.\n\n"
        "Можно написать текстом или отправить голосовое сообщение 🎤\n\n"
        "<i>Например: «Напиши приветственный пост для канала»</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb()
    )


@router.callback_query(F.data == "onboard:to_menu")
async def onboarding_to_menu(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    flags = await get_menu_flags(callback.from_user.id)
    await callback.message.answer("👇 Главное меню:", reply_markup=main_menu_kb(**flags))
