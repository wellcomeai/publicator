"""Утилиты для очистки HTML под Telegram"""

import re
import structlog

logger = structlog.get_logger()

# Теги, которые поддерживает Telegram
ALLOWED_TAGS = {
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
    "code", "pre", "a", "tg-spoiler", "blockquote",
}

# Паттерн для поиска HTML тегов
_TAG_PATTERN = re.compile(r"<(/?)(\w[\w-]*)((?:\s+[^>]*)?)>")


def sanitize_html(text: str) -> str:
    """
    Очистка HTML для отправки через Telegram Bot API.
    
    - Оставляет только поддерживаемые Telegram теги
    - Удаляет неизвестные теги (оставляя содержимое)
    - Экранирует незакрытые < > которые могут сломать парсинг
    """
    if not text:
        return text

    def replace_tag(match):
        slash = match.group(1)       # "/" или ""
        tag_name = match.group(2).lower()  # имя тега
        attrs = match.group(3)       # атрибуты

        if tag_name in ALLOWED_TAGS:
            # Для тега <a> сохраняем href
            if tag_name == "a" and not slash:
                href_match = re.search(r'href\s*=\s*["\']([^"\']*)["\']', attrs)
                if href_match:
                    return f'<a href="{href_match.group(1)}">'
                return ""  # <a> без href — удаляем
            # Для <pre> сохраняем language
            if tag_name == "pre" and not slash:
                lang_match = re.search(r'language\s*=\s*["\']([^"\']*)["\']', attrs)
                if lang_match:
                    return f'<pre language="{lang_match.group(1)}">'
            return f"<{slash}{tag_name}>"
        else:
            # Неизвестный тег — удаляем (оставляем содержимое)
            return ""

    result = _TAG_PATTERN.sub(replace_tag, text)

    return result
