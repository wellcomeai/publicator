"""Утилиты для работы с медиа и ссылками"""

import structlog
from typing import Dict, Any, Optional, List
from aiogram.types import Message

logger = structlog.get_logger()


def extract_media_info(message: Message) -> Optional[Dict[str, Any]]:
    """Извлечь информацию о медиа из сообщения (file_id + тип)"""
    
    if message.photo:
        # Берём максимальное разрешение (последний элемент)
        photo = message.photo[-1]
        return {
            "type": "photo",
            "file_id": photo.file_id,
            "file_unique_id": photo.file_unique_id,
        }
    
    if message.video:
        return {
            "type": "video",
            "file_id": message.video.file_id,
            "file_unique_id": message.video.file_unique_id,
        }
    
    if message.animation:
        return {
            "type": "animation",
            "file_id": message.animation.file_id,
            "file_unique_id": message.animation.file_unique_id,
        }
    
    if message.document:
        return {
            "type": "document",
            "file_id": message.document.file_id,
            "file_unique_id": message.document.file_unique_id,
            "file_name": message.document.file_name,
        }
    
    return None


def extract_links(message: Message) -> str:
    """Извлечь все ссылки из сообщения для передачи в prompt"""
    text = message.text or message.caption or ""
    entities = message.entities or message.caption_entities or []
    
    links = []
    for entity in entities:
        if entity.type == "url":
            url = text[entity.offset:entity.offset + entity.length]
            links.append(url)
        elif entity.type == "text_link":
            link_text = text[entity.offset:entity.offset + entity.length]
            links.append(f'{link_text} -> {entity.url}')
    
    return "\n".join(links) if links else ""


def get_text(message: Message) -> str:
    """Получить текст сообщения (text или caption)"""
    return (message.text or message.caption or "").strip()
