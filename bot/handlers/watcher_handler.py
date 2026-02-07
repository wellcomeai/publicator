"""
Хэндлер управления каналами-источниками (Channel Watcher).

Кнопка "📡 Источники" в главном меню.
Пользователь может:
- Посмотреть список отслеживаемых каналов
- Добавить канал (до лимита по плану)
- Удалить канал
- Нажать "Рерайт" на уведомлении о новом посте
"""

import json
import structlog
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from database.managers.user_manager import UserManager
from database.managers.agent_manager import AgentManager
from database.managers.post_manager import PostManager
from database.managers.watcher_manager import WatcherManager
from services.channel_watcher import validate_public_channel, fetch_new_posts
from services import openai_service
from bot.states.states import WatcherSetup
from bot.keyboards.keyboards import (
    watcher_menu_kb, watcher_post_kb, post_actions_kb, cancel_kb
)
from config.settings import config

logger = structlog.get_logger()
router = Router()


# ===== МЕНЮ ИСТОЧНИКОВ =====

@router.message(F.text == "📡 Источники")
async def watcher_menu(message: Message, state: FSMContext):
    """Показать список отслеживаемых каналов"""
    await state.clear()
    user = await UserManager.get_by_chat_id(message.from_user.id)
    if not user:
        await message.answer("Сначала нажмите /start")
        return

    plan = user.get("plan", "free")
    plan_config = config.PLANS.get(plan, config.PLANS["free"])
    max_channels = plan_config.get("watch_channels", 0)

    if max_channels == 0:
        await message.answer(
            "📡 <b>Источники контента</b>\n\n"
            "Автоматический мониторинг каналов доступен "
            "на тарифах <b>Стартер</b> и <b>Про</b>.\n\n"
            "Перейдите в раздел 💳 Подписка для апгрейда.",
            parse_mode="HTML"
        )
        return

    channels = await WatcherManager.get_user_channels(user["id"])
    current_count = len(channels)

    if channels:
        text = f"📡 <b>Источники контента ({current_count}/{max_channels}):</b>\n\n"
        for i, ch in enumerate(channels, 1):
            title = ch.get("channel_title") or ch["channel_username"]
            text += f"{i}. @{ch['channel_username']} — {title}\n"
        text += "\nНовые посты из этих каналов будут приходить вам автоматически."
    else:
        text = (
            "📡 <b>Источники контента</b>\n\n"
            "Добавьте публичные каналы, и бот будет присылать новые посты "
            "с предложением сделать рерайт.\n\n"
            f"Доступно: {max_channels} канал(ов)"
        )

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=watcher_menu_kb(channels, can_add=current_count < max_channels),
    )


# ===== ДОБАВЛЕНИЕ КАНАЛА =====

@router.callback_query(F.data == "watcher:add")
async def watcher_add_start(callback: CallbackQuery, state: FSMContext):
    """Начать добавление канала"""
    await callback.answer()
    await state.set_state(WatcherSetup.waiting_channel)

    await callback.message.answer(
        "📡 Введите @username или ссылку на публичный канал.\n\n"
        "<i>Примеры:\n"
        "• @durov\n"
        "• https://t.me/durov\n"
        "• durov</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb()
    )


@router.message(WatcherSetup.waiting_channel, F.text)
async def watcher_add_process(message: Message, state: FSMContext):
    """Обработка введённого канала"""
    user = await UserManager.get_by_chat_id(message.from_user.id)
    if not user:
        await message.answer("Сначала нажмите /start")
        return

    plan = user.get("plan", "free")
    plan_config = config.PLANS.get(plan, config.PLANS["free"])
    max_channels = plan_config.get("watch_channels", 0)
    current_count = await WatcherManager.count_user_channels(user["id"])

    if current_count >= max_channels:
        await message.answer(
            f"Достигнут лимит ({max_channels} каналов).\n"
            f"Удалите один из существующих или перейдите на тариф Про.",
        )
        await state.clear()
        return

    status_msg = await message.answer("Проверяю канал...")

    result = await validate_public_channel(message.text.strip())

    if not result["valid"]:
        await status_msg.edit_text(f"{result['error']}\n\nПопробуйте другой канал.")
        return

    username = result["username"]
    title = result.get("title", username)

    add_result = await WatcherManager.add_channel(
        user_id=user["id"],
        channel_username=username,
        channel_title=title,
    )

    if add_result.get("error"):
        await status_msg.edit_text(add_result["message"])
        await state.clear()
        return

    await state.clear()

    await status_msg.edit_text(
        f"Канал <b>@{username}</b> ({title}) добавлен!\n\n"
        f"Новые посты будут приходить автоматически.",
        parse_mode="HTML"
    )


# ===== УДАЛЕНИЕ КАНАЛА =====

@router.callback_query(F.data.startswith("watcher:remove:"))
async def watcher_remove(callback: CallbackQuery, state: FSMContext):
    """Удалить канал из отслеживания"""
    await callback.answer()
    watched_id = int(callback.data.split(":")[2])

    user = await UserManager.get_by_chat_id(callback.from_user.id)
    if not user:
        return

    success = await WatcherManager.remove_channel(watched_id, user["id"])

    if success:
        await callback.message.answer("Канал удалён из источников.")
    else:
        await callback.message.answer("Не удалось удалить канал.")


# ===== РЕРАЙТ ИЗ УВЕДОМЛЕНИЯ =====

@router.callback_query(F.data.startswith("watcher_rewrite:"))
async def watcher_rewrite_post(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """
    Рерайт поста из канала-источника.
    callback.data = "watcher_rewrite:{watched_channel_id}:{post_id}"
    """
    await callback.answer()
    parts = callback.data.split(":")
    watched_channel_id = int(parts[1])
    post_id = int(parts[2])

    user = await UserManager.get_by_chat_id(callback.from_user.id)
    if not user:
        return

    agent = await AgentManager.get_agent(user["id"])
    if not agent:
        await callback.message.answer("Сначала создайте ИИ-агента в разделе 🤖 Мой агент.")
        return

    has_tokens = await UserManager.has_tokens(callback.from_user.id)
    if not has_tokens:
        await callback.message.answer("Закончились токены. Докупите в разделе 💳 Подписка.")
        return

    channels = await WatcherManager.get_user_channels(user["id"])
    watched_channel = next((ch for ch in channels if ch["id"] == watched_channel_id), None)

    if not watched_channel:
        await callback.message.answer("Канал-источник не найден.")
        return

    status_msg = await callback.message.answer("Загружаю пост и делаю рерайт...")

    # Парсим пост повторно чтобы получить полный текст
    posts = await fetch_new_posts(
        watched_channel["channel_username"],
        after_post_id=post_id - 1
    )

    target_post = next((p for p in posts if p["post_id"] == post_id), None)

    if not target_post:
        await status_msg.edit_text("Не удалось загрузить пост. Возможно, он был удалён.")
        return

    original_text = target_post.get("text_html") or target_post["text"]
    source_link = target_post["link"]

    result = await openai_service.rewrite_post(
        original_text=original_text,
        agent_instructions=agent["instructions"],
        links_info=f"Источник: {source_link}",
        model=agent["model"],
    )

    if not result["success"]:
        await status_msg.edit_text(f"Ошибка рерайта: {result.get('error', 'Неизвестная ошибка')}")
        return

    total_tokens = result["total_tokens"]
    await UserManager.spend_tokens(callback.from_user.id, total_tokens)

    conversation_history = [
        {"role": "user", "content": f"Перепиши пост из @{watched_channel['channel_username']}:\n{original_text}"},
        {"role": "assistant", "content": result["text"]},
    ]

    post = await PostManager.create_post(
        user_id=user["id"],
        generated_text=result["text"],
        original_text=original_text,
        input_tokens=result["input_tokens"],
        output_tokens=result["output_tokens"],
        conversation_history=conversation_history,
    )

    await WatcherManager.mark_rewritten(watched_channel_id, post_id)

    await state.clear()
    await state.update_data(current_post_id=post["id"])

    try:
        await status_msg.delete()
    except Exception:
        pass

    from utils.html_sanitizer import sanitize_html
    tokens_note = f"\n\n<i>🪙 Использовано токенов: {total_tokens:,}</i>"
    full_text = sanitize_html(
        f"🔄 <b>Рерайт из @{watched_channel['channel_username']}:</b>\n\n"
        f"{result['text']}{tokens_note}"
    )

    plan = user.get("plan", "free")
    can_schedule = config.PLANS.get(plan, {}).get("allow_schedule", False)

    await bot.send_message(
        chat_id=callback.from_user.id,
        text=full_text,
        parse_mode="HTML",
        reply_markup=post_actions_kb(post["id"], can_schedule=can_schedule),
    )


# ===== ПРОПУСТИТЬ ПОСТ =====

@router.callback_query(F.data.startswith("watcher_skip:"))
async def watcher_skip_post(callback: CallbackQuery):
    """Пропустить пост — просто удаляем уведомление"""
    await callback.answer("Пропущено")
    try:
        await callback.message.delete()
    except Exception:
        pass
