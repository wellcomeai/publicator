"""Middleware для получения собранных медиагрупп (альбомов)

Буферизация и сбор альбомов происходит на уровне webhook (app.py).
Этот middleware только достаёт готовый альбом из буфера и передаёт в handler.
"""

import structlog
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import Message
from utils.album_buffer import retrieve_album

logger = structlog.get_logger()


class AlbumMiddleware(BaseMiddleware):
    """
    Middleware для передачи собранных медиагрупп в хэндлер.
    
    Альбомы собираются на уровне webhook handler (app.py) — там буферизуются
    все сообщения media_group и через 2 секунды подаются в dispatcher.
    
    Этот middleware достаёт собранный альбом из буфера.
    
    В хэндлере доступно через data["album"]:
    - Если сообщение — часть альбома: album = [Message, Message, ...]
    - Если одиночное сообщение: album = None
    """

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        if not event.media_group_id:
            # Одиночное сообщение
            data["album"] = None
            return await handler(event, data)

        # Достаём собранный альбом из буфера
        album_messages = retrieve_album(event.media_group_id)

        if album_messages and len(album_messages) > 1:
            data["album"] = album_messages
            logger.info("📸 Album passed to handler",
                        media_group_id=event.media_group_id,
                        count=len(album_messages))
        else:
            # Если по какой-то причине альбом не собрался — одиночное
            data["album"] = None
            logger.warning("⚠️ Album buffer empty, treating as single message",
                           media_group_id=event.media_group_id)

        return await handler(event, data)
