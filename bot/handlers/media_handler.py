"""Хэндлер управления медиа поста — генерация, загрузка, удаление, live preview"""

import json
import structlog
from typing import Optional, Dict, Any, List
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InputMediaPhoto, InputMediaVideo
from aiogram.fsm.context import FSMContext

from database.managers.user_manager import UserManager
from database.managers.agent_manager import AgentManager
from database.managers.post_manager import PostManager
from bot.states.states import MediaManagement
from bot.keyboards.keyboards import (
    post_actions_kb, media_actions_kb, image_prompt_kb,
    video_prompt_kb, video_duration_kb, media_upload_done_kb,
)
from services.media_manager import PostMediaManager
from services import image_service, video_service
from services.whisper_service import transcribe_voice
from utils.media import extract_media_info, get_text
from utils.html_sanitizer import sanitize_html

logger = structlog.get_logger()
router = Router()

CAPTION_MAX_LENGTH = 1024
MESSAGE_MAX_LENGTH = 4096


# ============================================================
#  LIVE PREVIEW
# ============================================================

async def send_live_preview(
    bot: Bot,
    chat_id: int,
    post_id: int,
    state: FSMContext,
    reply_markup=None,
    prefix: str = "📝",
    label: str = "Превью поста",
):
    """
    Отправить live preview поста: текст + все текущие медиа.
    Удаляет предыдущее превью и отправляет новое.
    """
    post = await PostManager.get_post(post_id)
    if not post:
        return

    text = post.get("final_text") or post.get("generated_text") or ""
    media_info = post.get("media_info")
    if media_info and isinstance(media_info, str):
        media_info = json.loads(media_info)

    # Удаляем старое превью
    data = await state.get_data()
    old_ids = data.get("preview_message_ids", [])
    for msg_id in old_ids:
        try:
            await bot.delete_message(chat_id, msg_id)
        except Exception:
            pass

    # Формируем текст
    items_count = PostMediaManager.get_items_count(media_info)
    media_list = PostMediaManager.format_media_list(media_info)
    media_note = f"\n\n📎 <b>Медиа ({items_count}):</b>\n{media_list}" if items_count > 0 else ""

    raw_caption = f"{prefix} <b>{label}:</b>\n\n{text}{media_note}"
    full_caption = sanitize_html(raw_caption)

    new_message_ids = []

    if not media_info or items_count == 0:
        # Без медиа — просто текст
        msg = await _send_text(bot, chat_id, full_caption, reply_markup=reply_markup)
        if msg:
            new_message_ids.append(msg.message_id)
    else:
        normalized = PostMediaManager.normalize_media_info(media_info)
        items = normalized.get("items", []) if normalized else []

        if len(items) == 1:
            # Одиночное медиа
            item = items[0]
            msg = await _send_single_media(bot, chat_id, item, full_caption, reply_markup)
            if msg:
                new_message_ids.append(msg.message_id)
        else:
            # Альбом
            media_group = _build_media_group(items, full_caption)
            if media_group:
                messages = await bot.send_media_group(chat_id, media_group)
                new_message_ids.extend([m.message_id for m in messages])

                # Если caption не влез — текст отдельно
                if len(full_caption) > CAPTION_MAX_LENGTH:
                    msg = await _send_text(bot, chat_id, full_caption)
                    if msg:
                        new_message_ids.append(msg.message_id)

            # Кнопки отдельным сообщением (для альбома)
            if reply_markup:
                msg = await bot.send_message(chat_id, "👆 Выберите действие:", reply_markup=reply_markup)
                new_message_ids.append(msg.message_id)

    await state.update_data(preview_message_ids=new_message_ids, current_post_id=post_id)


async def _send_text(bot: Bot, chat_id: int, text: str, reply_markup=None) -> Optional[Message]:
    """Отправка текста с разбиением"""
    text = sanitize_html(text)
    if len(text) <= MESSAGE_MAX_LENGTH:
        return await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode="HTML")

    parts = []
    while text:
        if len(text) <= MESSAGE_MAX_LENGTH:
            parts.append(text)
            break
        cut_pos = text.rfind("\n", 0, MESSAGE_MAX_LENGTH)
        if cut_pos <= 0:
            cut_pos = MESSAGE_MAX_LENGTH
        parts.append(text[:cut_pos])
        text = text[cut_pos:].lstrip("\n")

    last_msg = None
    for i, part in enumerate(parts):
        is_last = (i == len(parts) - 1)
        last_msg = await bot.send_message(
            chat_id, part,
            reply_markup=reply_markup if is_last else None,
            parse_mode="HTML",
        )
    return last_msg


async def _send_single_media(
    bot: Bot, chat_id: int, item: Dict, caption: str, reply_markup=None
) -> Optional[Message]:
    """Отправка одиночного медиа с caption"""
    media_type = item.get("type", "photo")
    file_id = item["file_id"]

    send_methods = {
        "photo": ("send_photo", "photo"),
        "video": ("send_video", "video"),
        "animation": ("send_animation", "animation"),
    }

    if media_type not in send_methods:
        return await _send_text(bot, chat_id, caption, reply_markup=reply_markup)

    method_name, param_name = send_methods[media_type]
    method = getattr(bot, method_name)

    if len(caption) <= CAPTION_MAX_LENGTH:
        return await method(
            chat_id, **{param_name: file_id},
            caption=caption, reply_markup=reply_markup, parse_mode="HTML",
        )
    else:
        await method(chat_id, **{param_name: file_id})
        return await _send_text(bot, chat_id, caption, reply_markup=reply_markup)


def _build_media_group(items: List[Dict], caption: str) -> List:
    """Собрать медиа-группу для отправки"""
    use_caption = len(caption) <= CAPTION_MAX_LENGTH
    media_group = []

    for i, item in enumerate(items):
        file_id = item["file_id"]
        item_type = item.get("type", "photo")
        cap = caption if (i == 0 and use_caption) else None
        parse = "HTML" if cap else None

        if item_type == "photo":
            media_group.append(InputMediaPhoto(media=file_id, caption=cap, parse_mode=parse))
        elif item_type == "video":
            media_group.append(InputMediaVideo(media=file_id, caption=cap, parse_mode=parse))

    return media_group


# ============================================================
#  МЕДИА-МЕНЮ
# ============================================================

@router.callback_query(F.data.startswith("media:"))
async def media_menu(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Показать меню управления медиа"""
    await callback.answer()
    post_id = int(callback.data.split(":")[1])

    # Удаляем сообщение с кнопками поста
    try:
        await callback.message.delete()
    except Exception:
        pass

    post = await PostManager.get_post(post_id)
    if not post:
        await bot.send_message(callback.from_user.id, "❌ Пост не найден.")
        return

    media_info = post.get("media_info")
    if media_info and isinstance(media_info, str):
        media_info = json.loads(media_info)

    items_count = PostMediaManager.get_items_count(media_info)
    media_list = PostMediaManager.format_media_list(media_info)

    text = (
        f"🖼 <b>Медиа поста</b>\n\n"
        f"{'📎 ' + media_list if items_count > 0 else '📭 Медиа пока нет.'}\n\n"
        f"Выберите действие:"
    )

    await state.set_state(MediaManagement.menu)
    await state.update_data(current_post_id=post_id)

    await bot.send_message(callback.from_user.id, text, parse_mode="HTML", reply_markup=media_actions_kb(post_id, items_count))


@router.callback_query(F.data.startswith("media_done:"))
async def media_done(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Выход из медиа-меню — возврат к посту"""
    await callback.answer()
    post_id = int(callback.data.split(":")[1])

    await state.clear()
    await state.update_data(current_post_id=post_id)

    await send_live_preview(
        bot=bot, chat_id=callback.from_user.id, post_id=post_id,
        state=state, reply_markup=post_actions_kb(post_id),
        prefix="📝", label="Превью поста",
    )


# ============================================================
#  ГЕНЕРАЦИЯ AI-КАРТИНКИ
# ============================================================

@router.callback_query(F.data.startswith("media_gen_image:"))
async def media_gen_image_start(callback: CallbackQuery, state: FSMContext):
    """Спросить промт или использовать авто"""
    await callback.answer()
    post_id = int(callback.data.split(":")[1])
    await state.update_data(current_post_id=post_id)

    await callback.message.answer(
        "🎨 <b>Генерация картинки (AI)</b>\n\n"
        "Выберите способ:",
        parse_mode="HTML",
        reply_markup=image_prompt_kb(post_id),
    )


@router.callback_query(F.data.startswith("media_gen_image_auto:"))
async def media_gen_image_auto(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Генерация картинки автоматически по теме поста"""
    await callback.answer()
    post_id = int(callback.data.split(":")[1])

    post = await PostManager.get_post(post_id)
    if not post:
        await callback.message.answer("❌ Пост не найден.")
        return

    media_info = post.get("media_info")
    if media_info and isinstance(media_info, str):
        media_info = json.loads(media_info)
    if PostMediaManager.get_items_count(media_info) >= PostMediaManager.MAX_ALBUM_SIZE:
        await callback.message.answer(f"⚠️ Максимум {PostMediaManager.MAX_ALBUM_SIZE} медиа в альбоме.")
        return

    status_msg = await callback.message.answer("🎨 Генерирую картинку по теме поста...")

    post_text = post.get("final_text") or post.get("generated_text") or ""
    prompt = await image_service.generate_image_prompt(post_text)

    image_result = await image_service.generate_image(
        prompt=prompt, bot=bot, chat_id=callback.from_user.id,
    )

    try:
        await status_msg.delete()
    except Exception:
        pass

    if not image_result:
        await callback.message.answer("❌ Не удалось сгенерировать картинку. Попробуйте ещё раз.")
        return

    result = await PostMediaManager.add_media_item(post_id, image_result)
    if result.get("error"):
        await callback.message.answer(f"⚠️ {result['message']}")
        return

    await send_live_preview(
        bot=bot, chat_id=callback.from_user.id, post_id=post_id,
        state=state,
        reply_markup=media_actions_kb(post_id, PostMediaManager.get_items_count(result)),
        prefix="🖼", label="Медиа обновлено",
    )


@router.callback_query(F.data.startswith("media_gen_image_custom:"))
async def media_gen_image_custom_start(callback: CallbackQuery, state: FSMContext):
    """Переход в ожидание пользовательского промта для картинки"""
    await callback.answer()
    post_id = int(callback.data.split(":")[1])

    await state.set_state(MediaManagement.waiting_ai_image_prompt)
    await state.update_data(current_post_id=post_id)

    await callback.message.answer(
        "🎨 Опишите, какую картинку сгенерировать.\n\n"
        "Можно написать текстом или отправить голосовое 🎤",
    )


@router.message(MediaManagement.waiting_ai_image_prompt, F.voice)
@router.message(MediaManagement.waiting_ai_image_prompt, F.text)
async def media_gen_image_custom(message: Message, state: FSMContext, bot: Bot):
    """Генерация картинки по пользовательскому промту"""
    data = await state.get_data()
    post_id = data.get("current_post_id")
    if not post_id:
        await message.answer("❌ Нет активного поста.")
        await state.clear()
        return

    # Получаем промт (текст или голос)
    if message.voice:
        status_msg = await message.answer("🎤 Распознаю голосовое сообщение...")
        prompt = await transcribe_voice(bot, message.voice)
        if not prompt:
            await status_msg.edit_text("❌ Не удалось распознать. Попробуйте ещё раз или напишите текстом.")
            return
        await status_msg.edit_text(f"✅ Распознано. Генерирую картинку...\n\n<i>«{prompt[:200]}»</i>", parse_mode="HTML")
    else:
        prompt = get_text(message)
        if not prompt:
            await message.answer("❌ Пустое сообщение. Опишите, какую картинку создать.")
            return
        status_msg = await message.answer("🎨 Генерирую картинку...")

    # Проверка лимита альбома
    media_info = await PostMediaManager.get_media(post_id)
    if PostMediaManager.get_items_count(media_info) >= PostMediaManager.MAX_ALBUM_SIZE:
        await status_msg.edit_text(f"⚠️ Максимум {PostMediaManager.MAX_ALBUM_SIZE} медиа в альбоме.")
        await state.set_state(MediaManagement.menu)
        return

    image_result = await image_service.generate_image(
        prompt=prompt, bot=bot, chat_id=message.from_user.id,
    )

    try:
        await status_msg.delete()
    except Exception:
        pass

    if not image_result:
        await message.answer("❌ Не удалось сгенерировать картинку. Попробуйте ещё раз.")
        await state.set_state(MediaManagement.menu)
        return

    result = await PostMediaManager.add_media_item(post_id, image_result)
    if result.get("error"):
        await message.answer(f"⚠️ {result['message']}")
        await state.set_state(MediaManagement.menu)
        return

    await state.set_state(MediaManagement.menu)
    await send_live_preview(
        bot=bot, chat_id=message.from_user.id, post_id=post_id,
        state=state,
        reply_markup=media_actions_kb(post_id, PostMediaManager.get_items_count(result)),
        prefix="🖼", label="Медиа обновлено",
    )


# ============================================================
#  ГЕНЕРАЦИЯ AI-ВИДЕО
# ============================================================

@router.callback_query(F.data.startswith("media_gen_video:"))
async def media_gen_video_start(callback: CallbackQuery, state: FSMContext):
    """Спросить промт или использовать авто"""
    await callback.answer()
    post_id = int(callback.data.split(":")[1])
    await state.update_data(current_post_id=post_id)

    await callback.message.answer(
        "🎬 <b>Генерация видео (AI)</b>\n\n"
        "Выберите способ:",
        parse_mode="HTML",
        reply_markup=video_prompt_kb(post_id),
    )


@router.callback_query(F.data.startswith("media_gen_video_auto:"))
async def media_gen_video_auto(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Выбор длительности для авто-промта"""
    await callback.answer()
    post_id = int(callback.data.split(":")[1])

    await callback.message.answer(
        "🎬 Выберите длительность видео:",
        reply_markup=video_duration_kb(post_id, "auto"),
    )


@router.callback_query(F.data.startswith("media_gen_video_custom:"))
async def media_gen_video_custom_start(callback: CallbackQuery, state: FSMContext):
    """Переход к выбору длительности, затем к вводу промта"""
    await callback.answer()
    post_id = int(callback.data.split(":")[1])

    await callback.message.answer(
        "🎬 Выберите длительность видео:",
        reply_markup=video_duration_kb(post_id, "custom"),
    )


@router.callback_query(F.data.startswith("media_video_dur:"))
async def media_video_duration_selected(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Обработка выбора длительности видео"""
    await callback.answer()
    parts = callback.data.split(":")
    duration = int(parts[1])
    post_id = int(parts[2])
    prompt_type = parts[3]  # "auto" или "custom"

    await state.update_data(current_post_id=post_id, video_duration=duration)

    if prompt_type == "auto":
        # Генерация по теме поста
        post = await PostManager.get_post(post_id)
        if not post:
            await callback.message.answer("❌ Пост не найден.")
            return

        media_info = post.get("media_info")
        if media_info and isinstance(media_info, str):
            media_info = json.loads(media_info)
        if PostMediaManager.get_items_count(media_info) >= PostMediaManager.MAX_ALBUM_SIZE:
            await callback.message.answer(f"⚠️ Максимум {PostMediaManager.MAX_ALBUM_SIZE} медиа в альбоме.")
            return

        status_msg = await callback.message.answer(f"🎬 Генерирую видео ({duration} сек)... Это может занять несколько минут.")

        post_text = post.get("final_text") or post.get("generated_text") or ""
        prompt = await video_service.generate_video_prompt(post_text)

        video_result = await video_service.generate_video(
            prompt=prompt, bot=bot, chat_id=callback.from_user.id,
            duration=duration, status_message=status_msg,
        )

        try:
            await status_msg.delete()
        except Exception:
            pass

        if not video_result:
            await callback.message.answer("❌ Не удалось сгенерировать видео. Попробуйте ещё раз.")
            return

        result = await PostMediaManager.add_media_item(post_id, video_result)
        if result.get("error"):
            await callback.message.answer(f"⚠️ {result['message']}")
            return

        await send_live_preview(
            bot=bot, chat_id=callback.from_user.id, post_id=post_id,
            state=state,
            reply_markup=media_actions_kb(post_id, PostMediaManager.get_items_count(result)),
            prefix="🎬", label="Медиа обновлено",
        )
    else:
        # Ждём пользовательский промт
        await state.set_state(MediaManagement.waiting_ai_video_prompt)
        await callback.message.answer(
            "🎬 Опишите, какое видео сгенерировать.\n\n"
            "Можно написать текстом или отправить голосовое 🎤",
        )


@router.message(MediaManagement.waiting_ai_video_prompt, F.voice)
@router.message(MediaManagement.waiting_ai_video_prompt, F.text)
async def media_gen_video_custom(message: Message, state: FSMContext, bot: Bot):
    """Генерация видео по пользовательскому промту"""
    data = await state.get_data()
    post_id = data.get("current_post_id")
    duration = data.get("video_duration", 4)

    if not post_id:
        await message.answer("❌ Нет активного поста.")
        await state.clear()
        return

    # Получаем промт
    if message.voice:
        status_msg = await message.answer("🎤 Распознаю голосовое сообщение...")
        prompt = await transcribe_voice(bot, message.voice)
        if not prompt:
            await status_msg.edit_text("❌ Не удалось распознать. Попробуйте ещё раз.")
            return
        await status_msg.edit_text(f"✅ Распознано. Генерирую видео ({duration} сек)...\n\n<i>«{prompt[:200]}»</i>", parse_mode="HTML")
    else:
        prompt = get_text(message)
        if not prompt:
            await message.answer("❌ Пустое сообщение. Опишите, какое видео создать.")
            return
        status_msg = await message.answer(f"🎬 Генерирую видео ({duration} сек)... Это может занять несколько минут.")

    # Проверка лимита альбома
    media_info = await PostMediaManager.get_media(post_id)
    if PostMediaManager.get_items_count(media_info) >= PostMediaManager.MAX_ALBUM_SIZE:
        await status_msg.edit_text(f"⚠️ Максимум {PostMediaManager.MAX_ALBUM_SIZE} медиа в альбоме.")
        await state.set_state(MediaManagement.menu)
        return

    video_result = await video_service.generate_video(
        prompt=prompt, bot=bot, chat_id=message.from_user.id,
        duration=duration, status_message=status_msg,
    )

    try:
        await status_msg.delete()
    except Exception:
        pass

    if not video_result:
        await message.answer("❌ Не удалось сгенерировать видео. Попробуйте ещё раз.")
        await state.set_state(MediaManagement.menu)
        return

    result = await PostMediaManager.add_media_item(post_id, video_result)
    if result.get("error"):
        await message.answer(f"⚠️ {result['message']}")
        await state.set_state(MediaManagement.menu)
        return

    await state.set_state(MediaManagement.menu)
    await send_live_preview(
        bot=bot, chat_id=message.from_user.id, post_id=post_id,
        state=state,
        reply_markup=media_actions_kb(post_id, PostMediaManager.get_items_count(result)),
        prefix="🎬", label="Медиа обновлено",
    )


# ============================================================
#  ЗАГРУЗКА СВОИХ МЕДИА
# ============================================================

@router.callback_query(F.data.startswith("media_upload:"))
async def media_upload_start(callback: CallbackQuery, state: FSMContext):
    """Перевести в режим ожидания загрузки"""
    await callback.answer()
    post_id = int(callback.data.split(":")[1])

    await state.set_state(MediaManagement.waiting_upload)
    await state.update_data(current_post_id=post_id)

    await callback.message.answer(
        "📎 Отправьте фото или видео. Можно несколько по одному.\n\n"
        "Когда закончите — нажмите «✅ Готово».",
        reply_markup=media_upload_done_kb(post_id),
    )


@router.message(MediaManagement.waiting_upload, F.photo)
async def media_upload_photo(message: Message, state: FSMContext, bot: Bot):
    """Принять загруженное фото"""
    data = await state.get_data()
    post_id = data.get("current_post_id")
    if not post_id:
        await message.answer("❌ Нет активного поста.")
        await state.clear()
        return

    photo = message.photo[-1]
    item = {
        "type": "photo",
        "file_id": photo.file_id,
        "file_unique_id": photo.file_unique_id,
        "source": "user_upload",
    }

    result = await PostMediaManager.add_media_item(post_id, item)
    if result.get("error"):
        await message.answer(f"⚠️ {result['message']}")
        return

    await send_live_preview(
        bot=bot, chat_id=message.from_user.id, post_id=post_id,
        state=state,
        reply_markup=media_upload_done_kb(post_id),
        prefix="🖼", label="Медиа обновлено",
    )


@router.message(MediaManagement.waiting_upload, F.video)
async def media_upload_video(message: Message, state: FSMContext, bot: Bot):
    """Принять загруженное видео"""
    data = await state.get_data()
    post_id = data.get("current_post_id")
    if not post_id:
        await message.answer("❌ Нет активного поста.")
        await state.clear()
        return

    item = {
        "type": "video",
        "file_id": message.video.file_id,
        "file_unique_id": message.video.file_unique_id,
        "source": "user_upload",
    }

    result = await PostMediaManager.add_media_item(post_id, item)
    if result.get("error"):
        await message.answer(f"⚠️ {result['message']}")
        return

    await send_live_preview(
        bot=bot, chat_id=message.from_user.id, post_id=post_id,
        state=state,
        reply_markup=media_upload_done_kb(post_id),
        prefix="🖼", label="Медиа обновлено",
    )


@router.message(MediaManagement.waiting_upload, F.animation)
async def media_upload_animation(message: Message, state: FSMContext, bot: Bot):
    """Принять загруженную анимацию (GIF)"""
    data = await state.get_data()
    post_id = data.get("current_post_id")
    if not post_id:
        await message.answer("❌ Нет активного поста.")
        await state.clear()
        return

    item = {
        "type": "animation",
        "file_id": message.animation.file_id,
        "file_unique_id": message.animation.file_unique_id,
        "source": "user_upload",
    }

    result = await PostMediaManager.add_media_item(post_id, item)
    if result.get("error"):
        await message.answer(f"⚠️ {result['message']}")
        return

    await send_live_preview(
        bot=bot, chat_id=message.from_user.id, post_id=post_id,
        state=state,
        reply_markup=media_upload_done_kb(post_id),
        prefix="🖼", label="Медиа обновлено",
    )


@router.callback_query(F.data.startswith("media_upload_done:"))
async def media_upload_done(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Завершение загрузки — возврат в медиа-меню"""
    await callback.answer()
    post_id = int(callback.data.split(":")[1])

    post = await PostManager.get_post(post_id)
    if not post:
        await callback.message.answer("❌ Пост не найден.")
        return

    media_info = post.get("media_info")
    if media_info and isinstance(media_info, str):
        media_info = json.loads(media_info)

    items_count = PostMediaManager.get_items_count(media_info)
    media_list = PostMediaManager.format_media_list(media_info)

    await state.set_state(MediaManagement.menu)
    await state.update_data(current_post_id=post_id)

    text = (
        f"🖼 <b>Медиа поста</b>\n\n"
        f"{'📎 ' + media_list if items_count > 0 else '📭 Медиа пока нет.'}\n\n"
        f"Выберите действие:"
    )
    await callback.message.answer(text, parse_mode="HTML", reply_markup=media_actions_kb(post_id, items_count))


# ============================================================
#  УДАЛЕНИЕ МЕДИА
# ============================================================

@router.callback_query(F.data.startswith("media_delete:"))
async def media_delete_start(callback: CallbackQuery, state: FSMContext):
    """Показать список медиа с номерами, попросить номер для удаления"""
    await callback.answer()
    post_id = int(callback.data.split(":")[1])

    media_info = await PostMediaManager.get_media(post_id)
    items_count = PostMediaManager.get_items_count(media_info)

    if items_count == 0:
        await callback.message.answer("📭 Нет медиа для удаления.")
        return

    media_list = PostMediaManager.format_media_list(media_info)

    await state.set_state(MediaManagement.waiting_delete_index)
    await state.update_data(current_post_id=post_id)

    await callback.message.answer(
        f"🗑 <b>Удаление медиа</b>\n\n"
        f"{media_list}\n\n"
        f"Введите номер медиа для удаления (1—{items_count}):",
        parse_mode="HTML",
    )


@router.message(MediaManagement.waiting_delete_index, F.text)
async def media_delete_process(message: Message, state: FSMContext, bot: Bot):
    """Удалить медиа по номеру"""
    data = await state.get_data()
    post_id = data.get("current_post_id")
    if not post_id:
        await message.answer("❌ Нет активного поста.")
        await state.clear()
        return

    try:
        index = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите номер (число).")
        return

    result = await PostMediaManager.remove_media_item(post_id, index)
    if result.get("error"):
        await message.answer(f"⚠️ {result['message']}")
        return

    items_count = len(result.get("items", []))

    await state.set_state(MediaManagement.menu)
    await state.update_data(current_post_id=post_id)

    await send_live_preview(
        bot=bot, chat_id=message.from_user.id, post_id=post_id,
        state=state,
        reply_markup=media_actions_kb(post_id, items_count),
        prefix="🗑", label="Медиа обновлено",
    )
