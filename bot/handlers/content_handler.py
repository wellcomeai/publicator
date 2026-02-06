"""Хэндлер создания, рерайта, редактирования и публикации контента"""

import json
import structlog
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
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
async def create_post_generate(message: Message, state: FSMContext):
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
    
    # Генерация через OpenAI
    result = await openai_service.generate_content(
        user_prompt=prompt,
        agent_instructions=agent["instructions"],
        model=agent["model"],
    )
    
    if not result["success"]:
        await status_msg.edit_text(f"❌ Ошибка генерации: {result.get('error', 'Неизвестная ошибка')}")
        return
    
    # Списываем токены
    total_tokens = result["total_tokens"]
    await UserManager.spend_tokens(message.from_user.id, total_tokens)
    
    # Сохраняем пост в БД
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
    
    await status_msg.edit_text(
        f"📝 <b>Сгенерированный пост:</b>\n\n"
        f"{result['text']}\n\n"
        f"<i>🪙 Использовано токенов: {total_tokens:,}</i>",
        reply_markup=post_actions_kb(post["id"]),
        parse_mode="HTML",
    )


# ============================================================
#  2. РЕРАЙТ ПОСТА (пересланный пост с медиа)
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
        "Поддерживаются посты с текстом, фото, видео и другими медиа.\n"
        "Медиа будет сохранено, а текст — переписан ИИ.",
        reply_markup=cancel_kb()
    )


@router.message(RewritePost.waiting_post)
async def rewrite_post_received(message: Message, state: FSMContext):
    """Обработка пересланного поста для рерайта"""
    user, error = await _check_prerequisites(message, state)
    if error:
        await message.answer(error)
        return
    
    original_text = get_text(message)
    if not original_text:
        await message.answer("❌ В сообщении нет текста для рерайта. Перешлите пост с текстом.")
        return
    
    agent = await AgentManager.get_agent(user["id"])
    
    # Извлекаем медиа (file_id) и ссылки
    media_info = extract_media_info(message)
    links_text = extract_links(message)
    
    status_msg = await message.answer("⏳ Переписываю пост...")
    
    # Рерайт через OpenAI
    result = await openai_service.rewrite_post(
        original_text=original_text,
        agent_instructions=agent["instructions"],
        links_info=links_text,
        model=agent["model"],
    )
    
    if not result["success"]:
        await status_msg.edit_text(f"❌ Ошибка рерайта: {result.get('error', 'Неизвестная ошибка')}")
        return
    
    # Списываем токены
    total_tokens = result["total_tokens"]
    await UserManager.spend_tokens(message.from_user.id, total_tokens)
    
    # Сохраняем пост с медиа
    conversation_history = [
        {"role": "user", "content": f"Перепиши пост:\n{original_text}"},
        {"role": "assistant", "content": result["text"]},
    ]
    
    post = await PostManager.create_post(
        user_id=user["id"],
        generated_text=result["text"],
        original_text=original_text,
        media_info=media_info,  # Сохраняем file_id!
        input_tokens=result["input_tokens"],
        output_tokens=result["output_tokens"],
        conversation_history=conversation_history,
    )
    
    await state.clear()
    await state.update_data(current_post_id=post["id"])
    
    media_note = ""
    if media_info:
        media_type_names = {"photo": "📷 Фото", "video": "🎥 Видео", "animation": "🎬 GIF", "document": "📎 Файл"}
        media_note = f"\n\n📎 Медиа: {media_type_names.get(media_info['type'], media_info['type'])} (будет сохранено)"
    
    await status_msg.edit_text(
        f"🔄 <b>Переписанный пост:</b>\n\n"
        f"{result['text']}"
        f"{media_note}\n\n"
        f"<i>🪙 Использовано токенов: {total_tokens:,}</i>",
        reply_markup=post_actions_kb(post["id"]),
        parse_mode="HTML",
    )


# ============================================================
#  3. МЕДИАГРУППЫ (альбомы)
# ============================================================

# Буфер для сбора медиагрупп
_album_buffer: dict = {}

@router.message(RewritePost.waiting_post, F.media_group_id)
async def rewrite_album_message(message: Message, state: FSMContext):
    """Сбор сообщений из медиагруппы"""
    import asyncio
    
    group_id = message.media_group_id
    
    if group_id not in _album_buffer:
        _album_buffer[group_id] = {
            "messages": [],
            "user_id": message.from_user.id,
            "state": state,
        }
    
    media = extract_media_info(message)
    _album_buffer[group_id]["messages"].append({
        "media": media,
        "text": get_text(message),
    })
    
    # Ждём 1 секунду чтобы собрать все сообщения группы
    await asyncio.sleep(1.0)
    
    # Если это первое сообщение, которое обрабатывается — начинаем рерайт
    if _album_buffer.get(group_id) and len(_album_buffer[group_id]["messages"]) > 0:
        album_data = _album_buffer.pop(group_id, None)
        if not album_data:
            return
        
        user, error = await _check_prerequisites(message, state)
        if error:
            await message.answer(error)
            return
        
        agent = await AgentManager.get_agent(user["id"])
        
        # Текст из первого сообщения (caption)
        original_text = ""
        for msg_data in album_data["messages"]:
            if msg_data["text"]:
                original_text = msg_data["text"]
                break
        
        if not original_text:
            await message.answer("❌ В альбоме нет текста для рерайта.")
            return
        
        # Собираем медиа
        album_items = []
        for msg_data in album_data["messages"]:
            if msg_data["media"]:
                album_items.append(msg_data["media"])
        
        media_info = {
            "type": "album",
            "items": album_items,
        }
        
        status_msg = await message.answer("⏳ Переписываю пост с альбомом...")
        
        result = await openai_service.rewrite_post(
            original_text=original_text,
            agent_instructions=agent["instructions"],
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
        
        await status_msg.edit_text(
            f"🔄 <b>Переписанный пост:</b>\n\n"
            f"{result['text']}\n\n"
            f"📎 Альбом: {len(album_items)} медиафайлов (будут сохранены)\n\n"
            f"<i>🪙 Использовано токенов: {total_tokens:,}</i>",
            reply_markup=post_actions_kb(post["id"]),
            parse_mode="HTML",
        )


# ============================================================
#  4. РЕДАКТИРОВАНИЕ (итеративное)
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
async def edit_post_process(message: Message, state: FSMContext):
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
    
    # Восстанавливаем историю
    conversation_history = post.get("conversation_history") or []
    if isinstance(conversation_history, str):
        conversation_history = json.loads(conversation_history)
    
    # Редактируем через OpenAI с контекстом
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
    
    # Списываем токены
    total_tokens = result["total_tokens"]
    await UserManager.spend_tokens(message.from_user.id, total_tokens)
    
    # Обновляем историю
    conversation_history.append({"role": "user", "content": edit_instruction})
    conversation_history.append({"role": "assistant", "content": result["text"]})
    
    # Обновляем пост
    await PostManager.update_post_text(
        post_id=post_id,
        new_text=result["text"],
        input_tokens=result["input_tokens"],
        output_tokens=result["output_tokens"],
        conversation_history=conversation_history,
    )
    
    await state.clear()
    await state.update_data(current_post_id=post_id)
    
    media_note = ""
    if post.get("media_info"):
        media_note = "\n\n📎 Медиа сохранено"
    
    await status_msg.edit_text(
        f"✏️ <b>Отредактированный пост:</b>\n\n"
        f"{result['text']}"
        f"{media_note}\n\n"
        f"<i>🪙 Использовано токенов: {total_tokens:,}</i>",
        reply_markup=post_actions_kb(post_id),
        parse_mode="HTML",
    )


# ============================================================
#  5. ПЕРЕГЕНЕРАЦИЯ
# ============================================================

@router.callback_query(F.data.startswith("regenerate:"))
async def regenerate_post(callback: CallbackQuery, state: FSMContext):
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
    
    # Определяем что делать: рерайт или генерацию
    original_text = post["original_text"]
    
    if post.get("media_info"):
        # Это был рерайт — повторяем рерайт
        result = await openai_service.rewrite_post(
            original_text=original_text,
            agent_instructions=agent["instructions"],
            model=agent["model"],
        )
    else:
        # Это была генерация — повторяем генерацию
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
    
    # Обновляем пост
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
    
    media_note = ""
    if post.get("media_info"):
        media_note = "\n\n📎 Медиа сохранено"
    
    await status_msg.edit_text(
        f"🔄 <b>Перегенерированный пост:</b>\n\n"
        f"{result['text']}"
        f"{media_note}\n\n"
        f"<i>🪙 Использовано токенов: {total_tokens:,}</i>",
        reply_markup=post_actions_kb(post_id),
        parse_mode="HTML",
    )


# ============================================================
#  6. ПУБЛИКАЦИЯ
# ============================================================

@router.callback_query(F.data.startswith("publish:"))
async def publish_post_handler(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    post_id = int(callback.data.split(":")[1])
    
    user = await UserManager.get_by_chat_id(callback.from_user.id)
    if not user:
        return
    
    # Проверяем канал
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
    media_info = post.get("media_info")
    
    # Parse media_info if string
    if isinstance(media_info, str):
        media_info = json.loads(media_info)
    
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
        await status_msg.edit_text(
            f"✅ Пост опубликован в {ch_display}!",
        )
        await state.clear()
    else:
        await status_msg.edit_text(
            f"❌ Ошибка публикации: {result.get('error', 'Неизвестная ошибка')}\n\n"
            f"Проверьте права бота в канале.",
        )


# ============================================================
#  7. ОТМЕНА / УДАЛЕНИЕ ЧЕРНОВИКА
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
