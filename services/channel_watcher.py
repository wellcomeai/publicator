"""
Сервис парсинга публичных Telegram-каналов через t.me/s/ web preview.

HTML-структура страницы t.me/s/{channel}:
- Каждый пост: <div class="tgme_widget_message_wrap">
    - Контейнер: <div class="tgme_widget_message" data-post="{channel}/{post_id}">
        - Текст: <div class="tgme_widget_message_text">...</div>
        - Фото: <a class="tgme_widget_message_photo_wrap" style="background-image:url('...')">
        - Видео: <a class="tgme_widget_message_video_wrap">
        - Просмотры: <span class="tgme_widget_message_views">...</span>
        - Дата: <time class="time" datetime="...">

Важно:
- Страница возвращает ~20 последних постов
- Для рерайта берём только текст, медиа не переносим
- Канал должен быть публичным
"""

import re
import structlog
import httpx
from typing import Optional, Dict, Any, List
from bs4 import BeautifulSoup

logger = structlog.get_logger()

REQUEST_TIMEOUT = 15.0
MIN_POST_TEXT_LENGTH = 50
MAX_PREVIEW_LENGTH = 300
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


async def validate_public_channel(channel_username: str) -> Dict[str, Any]:
    """
    Проверить что канал существует и публичный.

    Возвращает:
    {
        "valid": True/False,
        "title": "Название канала",
        "username": "durov",
        "error": "..." (если невалидный)
    }
    """
    username = _normalize_username(channel_username)
    if not username:
        return {"valid": False, "error": "Некорректное имя канала"}

    url = f"https://t.me/s/{username}"

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=REQUEST_TIMEOUT,
        ) as client:
            resp = await client.get(url, headers={"User-Agent": USER_AGENT})

        if resp.status_code != 200:
            return {"valid": False, "error": f"Канал не найден (HTTP {resp.status_code})"}

        if "tgme_page_description" not in resp.text and "tgme_channel_info" not in resp.text:
            if "tgme_widget_message" not in resp.text:
                return {"valid": False, "error": "Канал приватный или не существует"}

        soup = BeautifulSoup(resp.text, "html.parser")

        title_el = soup.select_one(".tgme_channel_info_header_title span")
        if not title_el:
            title_el = soup.select_one(".tgme_header_title")
        title = title_el.get_text(strip=True) if title_el else username

        posts = soup.select(".tgme_widget_message")
        if not posts:
            return {"valid": False, "error": "Канал пустой или приватный"}

        logger.info("Channel validated", username=username, title=title, posts=len(posts))

        return {
            "valid": True,
            "title": title,
            "username": username,
        }

    except httpx.TimeoutException:
        return {"valid": False, "error": "Таймаут при проверке канала"}
    except Exception as e:
        logger.error("Channel validation error", username=username, error=str(e))
        return {"valid": False, "error": f"Ошибка: {str(e)[:100]}"}


async def fetch_new_posts(channel_username: str, after_post_id: int = 0) -> List[Dict[str, Any]]:
    """
    Получить новые посты из публичного канала.

    Парсит https://t.me/s/{channel_username} и возвращает посты
    с post_id > after_post_id.

    Каждый пост:
    {
        "post_id": 317,
        "text": "Текст поста...",
        "text_html": "<b>Текст</b> поста...",
        "has_photo": True,
        "has_video": False,
        "link": "https://t.me/channel/317",
        "views": "1.2K",
        "date": "2025-02-07T10:30:00+00:00",
    }
    """
    username = _normalize_username(channel_username)
    if not username:
        return []

    url = f"https://t.me/s/{username}"

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=REQUEST_TIMEOUT,
        ) as client:
            resp = await client.get(url, headers={"User-Agent": USER_AGENT})

        if resp.status_code != 200:
            logger.warning("Failed to fetch channel", username=username, status=resp.status_code)
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        messages = soup.select(".tgme_widget_message")

        posts = []
        for msg in messages:
            data_post = msg.get("data-post", "")
            if "/" not in data_post:
                continue

            post_id = int(data_post.split("/")[-1])

            if post_id <= after_post_id:
                continue

            text_el = msg.select_one(".tgme_widget_message_text")
            if not text_el:
                continue

            text_plain = text_el.get_text(strip=True)

            if len(text_plain) < MIN_POST_TEXT_LENGTH:
                continue

            text_html = _extract_telegram_html(text_el)

            has_photo = bool(msg.select_one(".tgme_widget_message_photo_wrap"))
            has_video = bool(msg.select_one(".tgme_widget_message_video_wrap"))

            views_el = msg.select_one(".tgme_widget_message_views")
            views = views_el.get_text(strip=True) if views_el else ""

            time_el = msg.select_one("time.time")
            date_str = time_el.get("datetime", "") if time_el else ""

            posts.append({
                "post_id": post_id,
                "text": text_plain,
                "text_html": text_html,
                "has_photo": has_photo,
                "has_video": has_video,
                "link": f"https://t.me/{username}/{post_id}",
                "views": views,
                "date": date_str,
            })

        posts.sort(key=lambda p: p["post_id"])

        if posts:
            logger.info("New posts fetched",
                        channel=username,
                        count=len(posts),
                        after=after_post_id,
                        latest=posts[-1]["post_id"])

        return posts

    except Exception as e:
        logger.error("Failed to fetch posts", username=username, error=str(e))
        return []


def _normalize_username(raw: str) -> Optional[str]:
    """
    Нормализовать ввод пользователя:
    "@durov" -> "durov"
    "https://t.me/durov" -> "durov"
    "t.me/durov" -> "durov"
    "durov" -> "durov"
    """
    if not raw:
        return None

    raw = raw.strip()

    if raw.startswith("@"):
        raw = raw[1:]

    patterns = [
        r"https?://t\.me/s?/?",
        r"t\.me/s?/?",
    ]
    for pattern in patterns:
        raw = re.sub(pattern, "", raw)

    raw = raw.strip("/")
    if "/" in raw:
        raw = raw.split("/")[0]

    if not re.match(r"^[a-zA-Z][a-zA-Z0-9_]{3,}$", raw):
        return None

    return raw.lower()


def _extract_telegram_html(element) -> str:
    """
    Извлечь текст с базовым HTML-форматированием из элемента.
    Конвертирует теги Telegram web preview в Telegram Bot API HTML.
    """
    if not element:
        return ""

    html = element.decode_contents()

    html = re.sub(r"<br\s*/?>", "\n", html)

    from utils.html_sanitizer import sanitize_html
    result = sanitize_html(html)

    result = re.sub(r"\n{3,}", "\n\n", result)

    return result.strip()


def format_post_preview(post: Dict[str, Any], channel_username: str) -> str:
    """Форматировать пост для отправки пользователю как уведомление"""
    text = post["text"]
    if len(text) > MAX_PREVIEW_LENGTH:
        text = text[:MAX_PREVIEW_LENGTH] + "..."

    media_icon = ""
    if post.get("has_video"):
        media_icon = "🎬 "
    elif post.get("has_photo"):
        media_icon = "📷 "

    views_str = f"👁 {post['views']}" if post.get("views") else ""

    return (
        f"📥 <b>Новый пост в @{channel_username}:</b>\n\n"
        f"{media_icon}<i>{text}</i>\n\n"
        f"🔗 <a href=\"{post['link']}\">Оригинал</a>"
        f"{' | ' + views_str if views_str else ''}"
    )
