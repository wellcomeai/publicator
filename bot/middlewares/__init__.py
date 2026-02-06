"""Middleware для сбора медиагрупп (альбомов) в один батч"""

import asyncio
import structlog
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import Message

logger = structlog.get_logger()

# Буфер для сбора альбомов: {media_group_id: {"messages": [...], "processed": bool}}
_album_data: Dict[str, Dict] = {}
ALBUM_WAIT_SECONDS = 2.0  # Увеличено с 1.0 для надёжного сбора больших альбомов (7-10 фото)


class AlbumMiddleware(BaseMiddleware):
    """
    Middleware для сбора медиагрупп.
    
    Telegram отправляет каждый элемент альбома отдельным сообщением.
    Этот middleware собирает их в список и передаёт хэндлеру один раз.
    
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
            # Одиночное сообщение — пропускаем как обычно
            data["album"] = None
            return await handler(event, data)

        group_id = event.media_group_id

        if group_id not in _album_data:
            # Первое сообщение альбома — создаём буфер
            _album_data[group_id] = {
                "messages": [],
                "processed": False,
            }

        _album_data[group_id]["messages"].append(event)
        
        logger.debug("📸 Album message received",
                      media_group_id=group_id,
                      message_id=event.message_id,
                      buffered=len(_album_data[group_id]["messages"]))

        # Ждём чтобы собрать все сообщения группы
        await asyncio.sleep(ALBUM_WAIT_SECONDS)

        # Только первый «проснувшийся» обрабатывает
        if _album_data.get(group_id, {}).get("processed"):
            return  # Уже обработано другим сообщением

        _album_data[group_id]["processed"] = True
        messages = _album_data.pop(group_id, {}).get("messages", [])

        if not messages:
            return

        # Сортируем по message_id (порядок отправки)
        messages.sort(key=lambda m: m.message_id)

        logger.info("📸 Album collected",
                     media_group_id=group_id,
                     count=len(messages))

        # Передаём список сообщений в data["album"]
        data["album"] = messages

        # Вызываем хэндлер с первым сообщением (как основным)
        return await handler(messages[0], data)
