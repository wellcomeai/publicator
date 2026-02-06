"""Менеджер альбома поста — управление медиа-элементами"""

import json
import structlog
from typing import Optional, Dict, Any, List
from database.managers.post_manager import PostManager

logger = structlog.get_logger()


class PostMediaManager:
    """
    Управление медиа-альбомом поста.
    Альбом хранится в posts.media_info как JSONB.

    Формат альбома:
    {
        "type": "album",
        "items": [
            {"type": "photo", "file_id": "...", "file_unique_id": "...", "source": "ai_generated", "prompt": "..."},
            {"type": "video", "file_id": "...", "file_unique_id": "...", "source": "user_upload"},
        ]
    }

    Для одиночного медиа (обратная совместимость):
    {"type": "photo", "file_id": "...", "file_unique_id": "..."}

    Макс 10 элементов в альбоме.
    """

    MAX_ALBUM_SIZE = 10

    @staticmethod
    async def get_media(post_id: int) -> Optional[Dict]:
        """Получить текущее media_info поста"""
        post = await PostManager.get_post(post_id)
        if not post:
            return None
        media_info = post.get("media_info")
        if media_info and isinstance(media_info, str):
            media_info = json.loads(media_info)
        return media_info

    @staticmethod
    async def add_media_item(post_id: int, item: Dict) -> Dict:
        """
        Добавить медиа в альбом поста.
        Если media_info пусто — создаём новый альбом.
        Если уже есть одиночное медиа — конвертируем в альбом.
        Если альбом полный (10) — возвращаем ошибку.
        Возвращает обновлённый media_info.
        """
        current = await PostMediaManager.get_media(post_id)
        normalized = PostMediaManager.normalize_media_info(current)

        if normalized:
            items = normalized.get("items", [])
            if len(items) >= PostMediaManager.MAX_ALBUM_SIZE:
                return {"error": True, "message": f"Максимум {PostMediaManager.MAX_ALBUM_SIZE} медиа в альбоме"}
            items.append(item)
        else:
            items = [item]

        new_media_info = {
            "type": "album",
            "items": items,
        }

        await PostManager.update_media_info(post_id, new_media_info)
        logger.info("Media item added", post_id=post_id, items_count=len(items))
        return new_media_info

    @staticmethod
    async def remove_media_item(post_id: int, index: int) -> Dict:
        """
        Удалить медиа по индексу (1-based для пользователя).
        Если остаётся 0 элементов — ставим media_info = None.
        Возвращает обновлённый media_info.
        """
        current = await PostMediaManager.get_media(post_id)
        normalized = PostMediaManager.normalize_media_info(current)

        if not normalized:
            return {"error": True, "message": "Нет медиа для удаления"}

        items = normalized.get("items", [])
        idx = index - 1  # Конвертация из 1-based

        if idx < 0 or idx >= len(items):
            return {"error": True, "message": f"Неверный номер. Допустимые: 1—{len(items)}"}

        items.pop(idx)

        if not items:
            await PostManager.update_media_info(post_id, None)
            logger.info("All media removed", post_id=post_id)
            return {"type": "album", "items": []}

        new_media_info = {
            "type": "album",
            "items": items,
        }

        await PostManager.update_media_info(post_id, new_media_info)
        logger.info("Media item removed", post_id=post_id, index=index, remaining=len(items))
        return new_media_info

    @staticmethod
    async def clear_media(post_id: int) -> None:
        """Удалить все медиа поста"""
        await PostManager.update_media_info(post_id, None)
        logger.info("All media cleared", post_id=post_id)

    @staticmethod
    def get_items_count(media_info: Optional[Dict]) -> int:
        """Количество медиа-элементов"""
        if not media_info:
            return 0
        if media_info.get("type") == "album":
            return len(media_info.get("items", []))
        # Одиночное медиа
        if media_info.get("file_id"):
            return 1
        return 0

    @staticmethod
    def normalize_media_info(media_info: Optional[Dict]) -> Optional[Dict]:
        """
        Нормализация: одиночное медиа → альбом из 1 элемента (для единообразия).
        """
        if not media_info:
            return None

        if media_info.get("type") == "album":
            return media_info

        # Одиночное медиа → альбом
        if media_info.get("file_id"):
            return {
                "type": "album",
                "items": [media_info],
            }

        return None

    @staticmethod
    def format_media_list(media_info: Optional[Dict]) -> str:
        """Форматированный список медиа для отображения пользователю"""
        normalized = PostMediaManager.normalize_media_info(media_info)
        if not normalized:
            return "Нет медиа"

        items = normalized.get("items", [])
        if not items:
            return "Нет медиа"

        type_icons = {
            "photo": "🖼",
            "video": "🎬",
            "animation": "🎞",
            "document": "📄",
        }

        source_labels = {
            "ai_generated": "AI",
            "user_upload": "загружено",
        }

        lines = []
        for i, item in enumerate(items, 1):
            icon = type_icons.get(item.get("type", "photo"), "📎")
            source = source_labels.get(item.get("source", ""), "")
            source_str = f" ({source})" if source else ""
            media_type = "Фото" if item.get("type") == "photo" else "Видео" if item.get("type") == "video" else item.get("type", "")
            lines.append(f"{i}. {icon} {media_type}{source_str}")

        return "\n".join(lines)
