"""Извлечение текста из URL"""

import re
import structlog
import httpx
from typing import Optional, Dict, Any
from bs4 import BeautifulSoup

logger = structlog.get_logger()

MAX_CONTENT_SIZE = 5 * 1024 * 1024
REQUEST_TIMEOUT = 15.0
MIN_TEXT_LENGTH = 50


async def extract_text_from_url(url: str) -> Dict[str, Any]:
    """
    Извлечь текст и заголовок из URL.

    Возвращает:
    {
        "success": True/False,
        "title": "Заголовок статьи",
        "text": "Текст статьи...",
        "url": "https://...",
        "error": "..." (если неуспех)
    }
    """
    try:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; PublicatorAI/1.0)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
        }

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=REQUEST_TIMEOUT,
            max_redirects=5,
        ) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()

            content_length = len(response.content)
            if content_length > MAX_CONTENT_SIZE:
                return {"success": False, "error": "Страница слишком большая", "url": url}

            html = response.text

        soup = BeautifulSoup(html, "html.parser")

        # Удаляем ненужные элементы
        for tag in soup.find_all(["script", "style", "nav", "header", "footer",
                                   "aside", "iframe", "noscript", "form"]):
            tag.decompose()

        # Извлекаем заголовок
        title = ""
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()
        elif soup.title:
            title = soup.title.string.strip() if soup.title.string else ""
        elif soup.h1:
            title = soup.h1.get_text(strip=True)

        # Извлекаем основной текст
        content_element = None
        for selector in ["article", "main",
                         "[class*='article']", "[class*='content']",
                         "[class*='post-body']", "[class*='entry-content']"]:
            content_element = soup.select_one(selector)
            if content_element:
                break

        if not content_element:
            content_element = soup.body

        if not content_element:
            return {"success": False, "error": "Не удалось найти контент на странице", "url": url}

        # Извлекаем текст из параграфов
        paragraphs = content_element.find_all(["p", "h2", "h3", "li", "blockquote"])

        text_parts = []
        for p in paragraphs:
            text = p.get_text(strip=True)
            if len(text) > 20:
                text_parts.append(text)

        full_text = "\n\n".join(text_parts)

        if len(full_text) < MIN_TEXT_LENGTH:
            full_text = content_element.get_text(separator="\n\n", strip=True)

        if len(full_text) < MIN_TEXT_LENGTH:
            return {"success": False, "error": "На странице слишком мало текста", "url": url}

        # Ограничиваем длину (для GPT)
        if len(full_text) > 10000:
            full_text = full_text[:10000] + "..."

        logger.info("✅ URL text extracted",
                     url=url, title=title[:50], text_length=len(full_text))

        return {
            "success": True,
            "title": title,
            "text": full_text,
            "url": url,
        }

    except httpx.HTTPStatusError as e:
        logger.error("❌ HTTP error extracting URL", url=url, status=e.response.status_code)
        return {"success": False, "error": f"HTTP ошибка: {e.response.status_code}", "url": url}
    except httpx.TimeoutException:
        return {"success": False, "error": "Таймаут при загрузке страницы", "url": url}
    except Exception as e:
        logger.error("❌ Failed to extract URL", url=url, error=str(e))
        return {"success": False, "error": f"Ошибка: {str(e)[:100]}", "url": url}


def detect_url(text: str) -> Optional[str]:
    """
    Определить URL в тексте сообщения.
    Возвращает первый найденный URL или None.
    """
    url_pattern = re.compile(
        r'https?://[^\s<>"{}|\\^`\[\]]+|'
        r'www\.[^\s<>"{}|\\^`\[\]]+'
    )
    match = url_pattern.search(text)
    return match.group(0) if match else None
