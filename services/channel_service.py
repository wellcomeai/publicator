"""Сервис работы с каналами — проверка прав, публикация"""

import json
import structlog
from typing import Dict, Any, Optional, List
from aiogram import Bot
from aiogram.types import InputMediaPhoto, InputMediaVideo, InputMediaAnimation

logger = structlog.get_logger()


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


async def publish_post(
    bot: Bot,
    channel_id: int,
    text: str,
    media_info: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Опубликовать пост в канал.
    
    media_info format:
    - Single: {"type": "photo", "file_id": "...", "caption": "..."} 
    - Album: {"type": "album", "items": [{"type": "photo", "file_id": "..."}, ...]}
    """
    try:
        if not media_info:
            # Текстовый пост
            msg = await bot.send_message(channel_id, text, parse_mode="HTML")
            return {"success": True, "message_id": msg.message_id}
        
        media_type = media_info.get("type")
        
        if media_type == "album":
            # Медиаальбом
            return await _publish_album(bot, channel_id, text, media_info)
        
        elif media_type == "photo":
            msg = await bot.send_photo(
                channel_id,
                photo=media_info["file_id"],
                caption=text,
                parse_mode="HTML"
            )
            return {"success": True, "message_id": msg.message_id}
        
        elif media_type == "video":
            msg = await bot.send_video(
                channel_id,
                video=media_info["file_id"],
                caption=text,
                parse_mode="HTML"
            )
            return {"success": True, "message_id": msg.message_id}
        
        elif media_type == "animation":
            msg = await bot.send_animation(
                channel_id,
                animation=media_info["file_id"],
                caption=text,
                parse_mode="HTML"
            )
            return {"success": True, "message_id": msg.message_id}
        
        elif media_type == "document":
            msg = await bot.send_document(
                channel_id,
                document=media_info["file_id"],
                caption=text,
                parse_mode="HTML"
            )
            return {"success": True, "message_id": msg.message_id}
        
        else:
            # Неизвестный тип медиа — отправляем только текст
            logger.warning("⚠️ Unknown media type, sending text only", media_type=media_type)
            msg = await bot.send_message(channel_id, text, parse_mode="HTML")
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
    """Публикация медиаальбома"""
    try:
        items = media_info.get("items", [])
        if not items:
            return {"success": False, "error": "Empty album"}
        
        media_group = []
        for i, item in enumerate(items):
            item_type = item.get("type", "photo")
            file_id = item["file_id"]
            # Подпись только к первому элементу
            cap = caption_text if i == 0 else None
            
            if item_type == "photo":
                media_group.append(InputMediaPhoto(media=file_id, caption=cap, parse_mode="HTML" if cap else None))
            elif item_type == "video":
                media_group.append(InputMediaVideo(media=file_id, caption=cap, parse_mode="HTML" if cap else None))
        
        if not media_group:
            return {"success": False, "error": "No valid media items"}
        
        messages = await bot.send_media_group(channel_id, media_group)
        
        return {
            "success": True,
            "message_ids": [m.message_id for m in messages],
            "count": len(messages)
        }
    
    except Exception as e:
        logger.error("❌ Failed to publish album", channel_id=channel_id, error=str(e))
        return {"success": False, "error": str(e)}
