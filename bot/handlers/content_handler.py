"""Хэндлер создания, рерайта, редактирования и публикации контента"""

import json
import structlog
from typing import Optional, Dict, Any, List
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InputMediaPhoto, InputMediaVideo
from aiogram.fsm.context import FSMContext

from database.managers.user_manager import UserManager
from database.managers.agent_manager import AgentManager
from database.managers.channel_manager import ChannelManager
from database.managers.post_manager import PostManager
from bot.states.states import ContentGeneration, RewritePost
from bot.keyboards.keyboards import post_actions_kb, main_menu_kb, cancel_kb
from services import openai_service
from services.channel_service import publish_post
from utils.media import extract_media_info, extract_links, get_text

logger = structlog.get_logger()
router = Router()


# ============================================================
#  MIDDLEWARE-ПРОВЕРКИ
# ============================================================

async def _check_prerequisites(message_or_cb, state: FSMContext):
    """Общая проверка: пользователь + доступ + агент"""
    chat_id = message_or_cb.from_user.id

    user = await UserManager.get_by_chat_id(chat_id)
    if not user:
        return None, "Сначала нажмите /start"

    has_access = await UserManager.has_access(chat_id)
    if not has_access:
        return None, "⚠️ Нет активной подписки. Оформите подписку в разделе 💳 Подписка."

    has_tokens = await UserManager.has_tokens(chat_id)
    if not has_tokens:
        return None, "⚠️ Закончились токены. Докупите токены в разделе 💳 Подписка."

    agent = await AgentManager.get_agent(user["id"])
    if not agent:
        return None, "⚠️ Сначала создайте ИИ-агента в разделе 🤖 Мой агент."

    return user, None


# ============================================================
#  УТИЛИТЫ ДЛЯ ОТПРАВКИ МЕДИА-ПРЕВЬЮ
# ============================================================

async def _send_post_preview(
    bot: Bot,
    chat_id: int,
    text: str,
    media_info: Optional[Dict[str, Any]],
    reply_markup=None,
    tokens_used: int = 0,
    prefix: str = "📝",
    label: str = "Пост"
) -> Optional[Message]:
    """
    Отправка превью поста с медиа (если есть).
    """
    tokens_note = f"\n\n<i>🪙 Использовано токенов: {tokens_used:,}</i>" if tokens_used else ""
    full_caption = f"{prefix} <b>{label}:</b>\n\n{text}{tokens_note}"

    # Без медиа — просто текст
    if not media_info:
        return await bot.send_message(
            chat_id, full_caption,
            reply_markup=reply_markup, parse_mode="HTML",
        )

    media_type = media_info.get("type")

    # Альбом — отправляем группу + отдельное сообщение с кнопками
    if media_type == "album":
        items = media_info.get("items", [])
        if items:
            media_group = []
            for i, item in enumerate(items):
                file_id = item["file_id"]
                item_type = item.get("type", "photo")
                cap = full_caption if i == 0 else None
                parse = "HTML" if cap else None

                if item_type == "photo":
                    media_group.append(InputMediaPhoto(media=file_id, caption=cap, parse_mode=parse))
                elif item_type == "video":
                    media_group.append(InputMediaVideo(media=file_id, caption=cap, parse_mode=parse))

            if media_group:
                await bot.send_media_group(chat_id, media_group)
                if reply_markup:
                    return await bot.send_message(
                        chat_id, "👆 Выберите действие:",
                        reply_markup=reply_markup,
                    )
                return None

    # Одиночные медиа
    send_methods = {
        "photo": ("send_photo", "photo"),
        "video": ("send_video", "video"),
        "animation": ("send_animation", "animation"),
        "document": ("send_document", "document"),
    }

    if media_type in send_methods:
        method_name, param_name = send_methods[media_type]
        method = getattr(bot, method_name)
        return await method(
            chat_id,
            **{param_name: media_info["file_id"]},
            caption=full_caption,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )

    # Fallback — текстом
    return await bot.send_message(
        chat_id, full_caption,
        reply_markup=reply_markup, parse_mode="HTML",
    )


def _collect_album_media(album: List[Message]) -> Dict[str, Any]:
    """Собрать ВСЕ медиа из альбома"""
    items = []
    for msg in album:
        media = extract_media_info(msg)
        if media:
            items.append(media)

    return {
        "type": "album",
        "items": items,
        "count": len(items),
    }


def _parse_media_info(media_info) -> Optional[Dict[str, Any]]:
    """Парсинг media_info из БД (может быть строкой или dict)"""
    if not media_info:
        return None
    if isinstance(media_info, str):
        return json.loads(media_info)
    return media_info


# ============================================================
#  1. СОЗДАНИЕ ПОСТА
# ============================================================

@router.message(F.text == "✍️ Создать пост")
async def create_post_start(message: Message, state: FSMContext):
    await state.clear()
    user, error = await _check_prerequisites(message, state)
    if error:
        await message.answer(error)
        return

    await state.set_state(ContentGeneration.waiting_prompt)
    await message.answer(
        "✍️ Опишите, какой пост хотите создать.\n\n"
        "<i>Например: «Напиши пост про топ-5 трендов в ИИ на 2025 год»</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb()
    )


@router.message(ContentGeneration.waiting_prompt)
async def create_post_generate(message: Message, state: FSMContext, bot: Bot):
    user, error = await _check_prerequisites(message, state)
    if error:
        await message.answer(error)
        return

    agent = await AgentManager.get_agent(user["id"])
    prompt = get_text(message)

    if not prompt:
        await message.answer("❌ Пустое сообщение. Напишите, о чём создать пост.")
        return

    status_msg = await message.answer("⏳ Генерирую пост...")

    result = await openai_service.generate_content(
        user_prompt=prompt,
        agent_instructions=agent["instructions"],
        model=agent["model"],
    )

    if not result["success"]:
        await status_msg.edit_text(f"❌ Ошибка генерации: {result.get('error', 'Неизвестная ошибка')}")
        return

    total_tokens = result["total_tokens"]
    await UserManager.spend_tokens(message.from_user.id, total_tokens)

    conversation_history = [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": result["text"]},
    ]

    post = await PostManager.create_post(
        user_id=user["id"],
        generated_text=result["text"],
        original_text=prompt,
        input_tokens=result["input_tokens"],
        output_tokens=result["output_tokens"],
        conversation_history=conversation_history,
    )

    await state.clear()
    await state.update_data(current_post_id=post["id"])

    try:
        await status_msg.delete()
    except Exception:
        pass

    await _send_post_preview(
        bot=bot,
        chat_id=message.from_user.id,
        text=result["text"],
        media_info=None,
        reply_markup=post_actions_kb(post["id"]),
        tokens_used=total_tokens,
        prefix="📝",
        label="Сгенерированный пост",
    )


# ============================================================
#  2. РЕРАЙТ ПОСТА (одиночное + альбомы через AlbumMiddleware)
# ============================================================

@router.message(F.text == "🔄 Рерайт поста")
async def rewrite_post_start(message: Message, state: FSMContext):
    await state.clear()
    user, error = await _check_prerequisites(message, state)
    if error:
        await message.answer(error)
        return

    await state.set_state(RewritePost.waiting_post)
    await message.answer(
        "🔄 Перешлите мне пост, который хотите переписать.\n\n"
        "Поддерживаются посты с текстом, фото, видео и альбомами.\n"
        "Все медиа будут сохранены, а текст — переписан ИИ.",
        reply_markup=cancel_kb()
    )


@router.message(RewritePost.waiting_post)
async def rewrite_post_received(message: Message, state: FSMContext, bot: Bot, album: list = None):
    """Обработка пересланного поста (одиночного или альбома)"""
    user, error = await _check_prerequisites(message, state)
    if error:
        await message.answer(error)
        return

    # ===== СБОР ТЕКСТА И МЕДИА =====
    if album:
        # АЛЬБОМ: собираем текст из первого caption + все медиа
        original_text = ""
        links_text = ""
        for msg in album:
            txt = get_text(msg)
            if txt:
                original_text = txt
                links_text = extract_links(msg)
                break

        media_info = _collect_album_media(album)

        logger.info("📸 Album rewrite",
                     count=len(album),
                     media_items=len(media_info.get("items", [])),
                     has_text=bool(original_text))
    else:
        # ОДИНОЧНОЕ СООБЩЕНИЕ
        original_text = get_text(message)
        media_info = extract_media_info(message)
        links_text = extract_links(message)

    if not original_text:
        await message.answer("❌ В сообщении нет текста для рерайта. Перешлите пост с текстом.")
        return

    agent = await AgentManager.get_agent(user["id"])
    status_msg = await message.answer("⏳ Переписываю пост...")

    result = await openai_service.rewrite_post(
        original_text=original_text,
        agent_instructions=agent["instructions"],
        links_info=links_text,
        model=agent["model"],
    )

    if not result["success"]:
        await status_msg.edit_text(f"❌ Ошибка рерайта: {result.get('error', 'Неизвестная ошибка')}")
        return

    total_tokens = result["total_tokens"]
    await UserManager.spend_tokens(message.from_user.id, total_tokens)

    conversation_history = [
        {"role": "user", "content": f"Перепиши пост:\n{original_text}"},
        {"role": "assistant", "content": result["text"]},
    ]

    post = await PostManager.create_post(
        user_id=user["id"],
        generated_text=result["text"],
        original_text=original_text,
        media_info=media_info,
        input_tokens=result["input_tokens"],
        output_tokens=result["output_tokens"],
        conversation_history=conversation_history,
    )

    await state.clear()
    await state.update_data(current_post_id=post["id"])

    try:
        await status_msg.delete()
    except Exception:
        pass

    # ===== ПРЕВЬЮ С МЕДИА =====
    await _send_post_preview(
        bot=bot,
        chat_id=message.from_user.id,
        text=result["text"],
        media_info=media_info,
        reply_markup=post_actions_kb(post["id"]),
        tokens_used=total_tokens,
        prefix="🔄",
        label="Переписанный пост",
    )


# ============================================================
#  3. РЕДАКТИРОВАНИЕ
# ============================================================

@router.callback_query(F.data.startswith("edit:"))
async def edit_post_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    post_id = int(callback.data.split(":")[1])

    await state.set_state(ContentGeneration.waiting_edit)
    await state.update_data(current_post_id=post_id)

    await callback.message.answer(
        "✏️ Напишите, что нужно изменить.\n\n"
        "<i>Например: «Сделай короче», «Добавь больше эмодзи», «Измени заголовок»</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb()
    )


@router.message(ContentGeneration.waiting_edit)
async def edit_post_process(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    post_id = data.get("current_post_id")

    if not post_id:
        await message.answer("❌ Нет активного поста для редактирования.")
        await state.clear()
        return

    user, error = await _check_prerequisites(message, state)
    if error:
        await message.answer(error)
        return

    agent = await AgentManager.get_agent(user["id"])
    post = await PostManager.get_post(post_id)

    if not post:
        await message.answer("❌ Пост не найден.")
        await state.clear()
        return

    edit_instruction = get_text(message)
    if not edit_instruction:
        await message.answer("❌ Пустое сообщение. Опишите, что изменить.")
        return

    status_msg = await message.answer("⏳ Редактирую...")

    conversation_history = post.get("conversation_history") or []
    if isinstance(conversation_history, str):
        conversation_history = json.loads(conversation_history)

    result = await openai_service.edit_content(
        current_text=post["final_text"] or post["generated_text"],
        edit_instruction=edit_instruction,
        agent_instructions=agent["instructions"],
        conversation_history=conversation_history,
        model=agent["model"],
    )

    if not result["success"]:
        await status_msg.edit_text(f"❌ Ошибка редактирования: {result.get('error', 'Неизвестная ошибка')}")
        return

    total_tokens = result["total_tokens"]
    await UserManager.spend_tokens(message.from_user.id, total_tokens)

    conversation_history.append({"role": "user", "content": edit_instruction})
    conversation_history.append({"role": "assistant", "content": result["text"]})

    await PostManager.update_post_text(
        post_id=post_id,
        new_text=result["text"],
        input_tokens=result["input_tokens"],
        output_tokens=result["output_tokens"],
        conversation_history=conversation_history,
    )

    await state.clear()
    await state.update_data(current_post_id=post_id)

    try:
        await status_msg.delete()
    except Exception:
        pass

    media_info = _parse_media_info(post.get("media_info"))

    await _send_post_preview(
        bot=bot,
        chat_id=message.from_user.id,
        text=result["text"],
        media_info=media_info,
        reply_markup=post_actions_kb(post_id),
        tokens_used=total_tokens,
        prefix="✏️",
        label="Отредактированный пост",
    )


# ============================================================
#  4. ПЕРЕГЕНЕРАЦИЯ
# ============================================================

@router.callback_query(F.data.startswith("regenerate:"))
async def regenerate_post(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    post_id = int(callback.data.split(":")[1])

    post = await PostManager.get_post(post_id)
    if not post or not post.get("original_text"):
        await callback.message.answer("❌ Невозможно перегенерировать — нет исходного запроса.")
        return

    user = await UserManager.get_by_chat_id(callback.from_user.id)
    if not user:
        return

    agent = await AgentManager.get_agent(user["id"])
    if not agent:
        await callback.message.answer("⚠️ Агент не найден.")
        return

    has_tokens = await UserManager.has_tokens(callback.from_user.id)
    if not has_tokens:
        await callback.message.answer("⚠️ Закончились токены.")
        return

    status_msg = await callback.message.answer("⏳ Перегенерирую...")

    original_text = post["original_text"]

    if post.get("media_info"):
        result = await openai_service.rewrite_post(
            original_text=original_text,
            agent_instructions=agent["instructions"],
            model=agent["model"],
        )
    else:
        result = await openai_service.generate_content(
            user_prompt=original_text,
            agent_instructions=agent["instructions"],
            model=agent["model"],
        )

    if not result["success"]:
        await status_msg.edit_text(f"❌ Ошибка: {result.get('error', 'Неизвестная ошибка')}")
        return

    total_tokens = result["total_tokens"]
    await UserManager.spend_tokens(callback.from_user.id, total_tokens)

    conversation_history = [
        {"role": "user", "content": original_text},
        {"role": "assistant", "content": result["text"]},
    ]

    await PostManager.update_post_text(
        post_id=post_id,
        new_text=result["text"],
        input_tokens=result["input_tokens"],
        output_tokens=result["output_tokens"],
        conversation_history=conversation_history,
    )

    try:
        await status_msg.delete()
    except Exception:
        pass

    media_info = _parse_media_info(post.get("media_info"))

    await _send_post_preview(
        bot=bot,
        chat_id=callback.from_user.id,
        text=result["text"],
        media_info=media_info,
        reply_markup=post_actions_kb(post_id),
        tokens_used=total_tokens,
        prefix="🔄",
        label="Перегенерированный пост",
    )


# ============================================================
#  5. ПУБЛИКАЦИЯ
# ============================================================

@router.callback_query(F.data.startswith("publish:"))
async def publish_post_handler(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    post_id = int(callback.data.split(":")[1])

    user = await UserManager.get_by_chat_id(callback.from_user.id)
    if not user:
        return

    channel = await ChannelManager.get_channel(user["id"])
    if not channel:
        await callback.message.answer(
            "⚠️ Канал не привязан. Привяжите канал в разделе 📢 Мой канал."
        )
        return

    post = await PostManager.get_post(post_id)
    if not post:
        await callback.message.answer("❌ Пост не найден.")
        return

    text_to_publish = post["final_text"] or post["generated_text"]
    media_info = _parse_media_info(post.get("media_info"))

    status_msg = await callback.message.answer("⏳ Публикую в канал...")

    result = await publish_post(
        bot=bot,
        channel_id=channel["channel_id"],
        text=text_to_publish,
        media_info=media_info,
    )

    if result["success"]:
        await PostManager.mark_published(post_id, channel["channel_id"])
        ch_display = f"@{channel['channel_username']}" if channel.get("channel_username") else channel.get("channel_title", "канал")
        await status_msg.edit_text(f"✅ Пост опубликован в {ch_display}!")
        await state.clear()
    else:
        await status_msg.edit_text(
            f"❌ Ошибка публикации: {result.get('error', 'Неизвестная ошибка')}\n\n"
            f"Проверьте права бота в канале.",
        )


# ============================================================
#  6. ОТМЕНА / УДАЛЕНИЕ ЧЕРНОВИКА
# ============================================================

@router.callback_query(F.data.startswith("discard:"))
async def discard_post(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    post_id = int(callback.data.split(":")[1])
    await PostManager.discard_draft(post_id)
    await state.clear()
    await callback.message.answer("🗑 Черновик удалён.", reply_markup=main_menu_kb())


@router.callback_query(F.data == "cancel")
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Отменено")
    await state.clear()
    await callback.message.answer("Действие отменено.", reply_markup=main_menu_kb())
