"""OpenAI сервис — генерация и рерайт контента через GPT-4o-mini"""

import structlog
from typing import Dict, Any, List, Optional
from openai import AsyncOpenAI
from config.settings import config

logger = structlog.get_logger()

client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)


SYSTEM_PROMPT_BASE = """<role>
Ты — профессиональный контент-менеджер Telegram-каналов. Твоя задача — создавать вовлекающие посты, которые публикуются вместе с медиа (фото/видео).
</role>

<critical_constraint>
ЖЁСТКИЙ ЛИМИТ: максимум 900 символов на пост, включая пробелы и HTML-теги. Это ~120-150 слов. Посты публикуются в Telegram как caption к медиа, где лимит 1024 символа. НИКОГДА не превышай 900 символов. Если текст длиннее — он будет обрезан и пост сломается.
</critical_constraint>

<format_rules>
- Язык: русский
- Форматирование: только HTML-теги Telegram: <b>жирный</b>, <i>курсив</i>, <u>подчёркнутый</u>, <code>код</code>, <a href="url">ссылка</a>
- ЗАПРЕЩЕНО: Markdown, хештеги (если их нет в оригинале), чрезмерные эмодзи
- Сохраняй все ссылки из оригинального текста
</format_rules>

<structure>
Оптимальная структура поста:
1. Цепляющий заголовок (1 строка, можно с эмодзи)
2. Основной текст (2-4 абзаца)
3. Вывод или призыв к действию (1 строка)

Разделяй абзацы пустой строкой для читаемости.
</structure>

<quality_checklist>
Перед ответом проверь:
☐ Текст ≤ 900 символов (считай с HTML-тегами и пробелами)
☐ Текст вовлекающий и полезный для аудитории
☐ Нет обрезанных предложений
☐ Структура логична и завершена
</quality_checklist>"""


async def generate_content(
    user_prompt: str,
    agent_instructions: str,
    conversation_history: List[Dict[str, str]] = None,
    model: str = None
) -> Dict[str, Any]:
    """
    Генерация / редактирование контента.
    
    conversation_history: список {"role": "user"/"assistant", "content": "..."}
    для поддержки итеративного редактирования.
    """
    model = model or config.OPENAI_MODEL

    system_message = f"{SYSTEM_PROMPT_BASE}\n\nИНСТРУКЦИИ АВТОРА КАНАЛА:\n{agent_instructions}"

    messages = [{"role": "system", "content": system_message}]

    # Добавляем историю диалога (для редактирования)
    if conversation_history:
        messages.extend(conversation_history)

    messages.append({"role": "user", "content": user_prompt})

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=2000,
            temperature=0.7,
        )

        choice = response.choices[0]
        generated_text = choice.message.content.strip()

        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        logger.info("✅ Content generated",
                     model=model,
                     input_tokens=input_tokens,
                     output_tokens=output_tokens,
                     output_length=len(generated_text))

        return {
            "success": True,
            "text": generated_text,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "model": model,
        }

    except Exception as e:
        logger.error("❌ OpenAI generation failed", error=str(e))
        return {
            "success": False,
            "error": str(e),
            "text": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }


CONFIRM_PLAN_TOOL = {
    "type": "function",
    "function": {
        "name": "confirm_content_plan",
        "description": (
            "Вызови эту функцию ТОЛЬКО когда пользователь ЯВНО подтвердил контент-план. "
            "Не вызывай без явного согласия (слова: да, подтверждаю, ок, погнали, запускай, всё верно)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topics": {
                    "type": "array",
                    "description": "Массив тем контент-плана в порядке публикации",
                    "items": {
                        "type": "object",
                        "properties": {
                            "topic": {
                                "type": "string",
                                "description": "Тема поста"
                            },
                            "format": {
                                "type": "string",
                                "enum": ["пост", "лонгрид", "список", "история", "кейс", "инструкция", "обзор"],
                                "description": "Формат контента"
                            },
                            "description": {
                                "type": "string",
                                "description": "Краткое описание: о чём именно пост (1-2 предложения)"
                            }
                        },
                        "required": ["topic", "format", "description"]
                    }
                }
            },
            "required": ["topics"]
        }
    }
}


def build_plan_system_prompt(
    agent_instructions: str,
    channel_name: str,
    slots_count: int,
    schedule_info: str
) -> str:
    """
    Строит системный промт для диалога по контент-плану.

    Args:
        agent_instructions: инструкции агента пользователя (тон, стиль, тематика)
        channel_name: название канала
        slots_count: количество слотов в расписании (сколько постов нужно)
        schedule_info: текстовое описание расписания ("Пн 10:00, Ср 14:00, Пт 18:00")
    """
    return f"""Ты — ИИ-помощник для планирования контента в Telegram-канал "{channel_name}".

ТВОЯ ЗАДАЧА: помочь пользователю составить контент-план на ближайший период.

КОНТЕКСТ КАНАЛА:
{agent_instructions}

РАСПИСАНИЕ ПУБЛИКАЦИЙ:
- Количество постов для плана: {slots_count}
- Слоты: {schedule_info}

ПРАВИЛА:
1. Предложи {slots_count} тем для постов, учитывая тематику канала
2. Для каждой темы укажи формат (пост, лонгрид, список, история, кейс, инструкция, обзор)
3. Обсуди с пользователем — он может менять темы, порядок, форматы
4. Будь гибким: принимай предложения пользователя, предлагай альтернативы
5. Когда пользователь подтвердит план — вызови функцию confirm_content_plan

⚠️ КРИТИЧЕСКИ ВАЖНО:
- Вызывай confirm_content_plan ТОЛЬКО после ЯВНОГО подтверждения пользователя
- Слова подтверждения: "да", "подтверждаю", "ок", "запускай", "всё верно", "погнали", "го"
- НИКОГДА не вызывай функцию, если пользователь ещё обсуждает, сомневается или просит изменения
- Если пользователь просто говорит "хорошо" в контексте обсуждения — это НЕ подтверждение, уточни

ФОРМАТ ОТВЕТОВ:
- Представляй план в виде нумерованного списка
- Для каждого пункта: номер, тема, формат в скобках, краткое описание
- Будь лаконичным, не перегружай текст"""


async def rewrite_post(
    original_text: str,
    agent_instructions: str,
    links_info: str = "",
    model: str = None
) -> Dict[str, Any]:
    """Рерайт поста с сохранением ссылок"""

    prompt = (
        "Перепиши следующий пост для Telegram-канала.\n"
        "ВАЖНО: результат СТРОГО до 900 символов включая HTML-теги и пробелы.\n"
        "Сохрани ключевой смысл, адаптируй под стиль канала.\n\n"
        f"Оригинал:\n{original_text}"
    )

    if links_info:
        prompt += f"\n\nОБЯЗАТЕЛЬНО сохрани эти ссылки:\n{links_info}"

    return await generate_content(
        user_prompt=prompt,
        agent_instructions=agent_instructions,
        model=model
    )


async def edit_content(
    current_text: str,
    edit_instruction: str,
    agent_instructions: str,
    conversation_history: List[Dict[str, str]] = None,
    model: str = None
) -> Dict[str, Any]:
    """Редактирование контента с учётом контекста"""

    # Строим историю для контекста
    history = conversation_history or []

    prompt = (
        f"Текущий текст поста:\n\n{current_text}\n\n"
        f"Задача: {edit_instruction}\n\n"
        f"ВАЖНО: результат СТРОГО до 900 символов включая HTML-теги и пробелы. "
        f"Не превышай этот лимит."
    )

    return await generate_content(
        user_prompt=prompt,
        agent_instructions=agent_instructions,
        conversation_history=history,
        model=model
    )
