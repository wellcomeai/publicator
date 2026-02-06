"""Сервис работы с каналами — проверка прав, публикация"""

import json
import structlog
from typing import Dict, Any, Optional, List
from aiogram import Bot
from aiogram.types import InputMediaPhoto, InputMediaVideo, InputMediaAnimation

logger = structlog.get_logger()

# Telegram ограничивает caption медиа до 1024 символов
CAPTION_MAX_LENGTH = 1024
# Telegram ограничивает текстовые сообщения до 4096 символов
MESSAGE_MAX_LENGTH = 4096


async def verify_bot_is_admin(bot: Bot, channel_id: int) -> Dict[str, Any]:
    """Проверить что бот — администратор канала с правом публикации"""
    try:
        member = await bot.get_chat_member(channel_id, bot.id)
        
        is_admin = member.status in ("administrator", "creator")
        can_post = False
        
        if member.status == "creator":
            can_post = True
        elif member.status == "administrator":
            can_post = getattr(member, "can_post_messages", False)
        
        return {
            "is_admin": is_admin,
            "can_post": can_post,
            "status": member.status,
        }
    except Exception as e:
        logger.error("❌ Failed to check bot admin status", channel_id=channel_id, error=str(e))
        return {"is_admin": False, "can_post": False, "error": str(e)}


async def _send_long_text(bot: Bot, channel_id: int, text: str, parse_mode: str = "HTML") -> Any:
    """
    Отправка длинного текста с разбиением на части (если > 4096 символов).
    """
    if len(text) <= MESSAGE_MAX_LENGTH:
        return await bot.send_message(channel_id, text, parse_mode=parse_mode)

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
    for part in parts:
        last_msg = await bot.send_message(channel_id, part, parse_mode=parse_mode)
    return last_msg


async def publish_post(
    bot: Bot,
    channel_id: int,
    text: str,
    media_info: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Опубликовать пост в канал.
    
    Если caption > 1024 символов — медиа отправляется без подписи,
    текст отправляется отдельным сообщением.
    
    media_info format:
    - Single: {"type": "photo", "file_id": "...", "caption": "..."} 
    - Album: {"type": "album", "items": [{"type": "photo", "file_id": "..."}, ...]}
    """
    try:
        if not media_info:
            # Текстовый пост
            msg = await _send_long_text(bot, channel_id, text)
            return {"success": True, "message_id": msg.message_id}
        
        media_type = media_info.get("type")
        
        if media_type == "album":
            # Медиаальбом
            return await _publish_album(bot, channel_id, text, media_info)
        
        # === ОДИНОЧНЫЕ МЕДИА ===
        send_map = {
            "photo": ("send_photo", "photo"),
            "video": ("send_video", "video"),
            "animation": ("send_animation", "animation"),
            "document": ("send_document", "document"),
        }
        
        if media_type in send_map:
            method_name, param_name = send_map[media_type]
            method = getattr(bot, method_name)
            
            if len(text) <= CAPTION_MAX_LENGTH:
                # Caption влезает — отправляем медиа с подписью
                msg = await method(
                    channel_id,
                    **{param_name: media_info["file_id"]},
                    caption=text,
                    parse_mode="HTML",
                )
                return {"success": True, "message_id": msg.message_id}
            else:
                # Caption слишком длинный — медиа без подписи, текст отдельно
                await method(
                    channel_id,
                    **{param_name: media_info["file_id"]},
                )
                msg = await _send_long_text(bot, channel_id, text)
                return {"success": True, "message_id": msg.message_id}
        
        # Неизвестный тип медиа — отправляем только текст
        logger.warning("⚠️ Unknown media type, sending text only", media_type=media_type)
        msg = await _send_long_text(bot, channel_id, text)
        return {"success": True, "message_id": msg.message_id}
    
    except Exception as e:
        logger.error("❌ Failed to publish post", channel_id=channel_id, error=str(e))
        return {"success": False, "error": str(e)}


async def _publish_album(
    bot: Bot,
    channel_id: int,
    caption_text: str,
    media_info: Dict[str, Any]
) -> Dict[str, Any]:
    """Публикация медиаальбома с проверкой длины caption"""
    try:
        items = media_info.get("items", [])
        if not items:
            return {"success": False, "error": "Empty album"}
        
        use_caption = len(caption_text) <= CAPTION_MAX_LENGTH
        
        media_group = []
        for i, item in enumerate(items):
            item_type = item.get("type", "photo")
            file_id = item["file_id"]
            # Подпись только к первому элементу и только если влезает
            cap = caption_text if (i == 0 and use_caption) else None
            
            if item_type == "photo":
                media_group.append(InputMediaPhoto(
                    media=file_id,
                    caption=cap,
                    parse_mode="HTML" if cap else None,
                ))
            elif item_type == "video":
                media_group.append(InputMediaVideo(
                    media=file_id,
                    caption=cap,
                    parse_mode="HTML" if cap else None,
                ))
        
        if not media_group:
            return {"success": False, "error": "No valid media items"}
        
        messages = await bot.send_media_group(channel_id, media_group)
        
        # Если caption не влез — отправляем текст отдельным сообщением
        if not use_caption:
            await _send_long_text(bot, channel_id, caption_text)
        
        return {
            "success": True,
            "message_ids": [m.message_id for m in messages],
            "count": len(messages),
        }
    
    except Exception as e:
        logger.error("❌ Failed to publish album", channel_id=channel_id, error=str(e))
        return {"success": False, "error": str(e)}
