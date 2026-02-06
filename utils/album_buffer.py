"""Глобальный буфер для сбора медиагрупп (альбомов) на уровне webhook"""

import asyncio
import structlog
from typing import Dict, List, Optional
from aiogram.types import Message

logger = structlog.get_logger()

# Хранилище собранных альбомов: {media_group_id: [Message, ...]}
_collected_albums: Dict[str, List[Message]] = {}

# Буфер для сбора: {media_group_id: [Message, ...]}
_pending_buffer: Dict[str, List[Message]] = {}

ALBUM_WAIT_SECONDS = 2.0


def store_album(media_group_id: str, messages: List[Message]):
    """Сохранить собранный альбом для последующего получения в middleware"""
    _collected_albums[media_group_id] = messages


def retrieve_album(media_group_id: str) -> Optional[List[Message]]:
    """Получить и удалить собранный альбом (вызывается из middleware)"""
    return _collected_albums.pop(media_group_id, None)


def add_to_buffer(media_group_id: str, message: Message) -> bool:
    """
    Добавить сообщение в буфер сбора.
    Возвращает True если это ПЕРВОЕ сообщение группы (нужно запустить таймер).
    """
    is_first = media_group_id not in _pending_buffer
    if is_first:
        _pending_buffer[media_group_id] = []
    _pending_buffer[media_group_id].append(message)

    logger.debug("📸 Album message buffered",
                 media_group_id=media_group_id,
                 message_id=message.message_id,
                 buffered=len(_pending_buffer[media_group_id]))

    return is_first


def flush_buffer(media_group_id: str) -> List[Message]:
    """Забрать все сообщения из буфера и отсортировать"""
    messages = _pending_buffer.pop(media_group_id, [])
    messages.sort(key=lambda m: m.message_id)

    logger.info("📸 Album flushed from buffer",
                media_group_id=media_group_id,
                count=len(messages))

    return messages
