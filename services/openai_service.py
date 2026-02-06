"""OpenAI сервис — генерация и рерайт контента через GPT-4o-mini"""

import structlog
from typing import Dict, Any, List, Optional
from openai import AsyncOpenAI
from config.settings import config

logger = structlog.get_logger()

client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)


SYSTEM_PROMPT_BASE = """Ты — профессиональный контент-менеджер для Telegram-каналов.

ПРАВИЛА:
- Пиши на русском языке
- Используй HTML-форматирование для Telegram: <b>жирный</b>, <i>курсив</i>, <u>подчёркнутый</u>, <code>код</code>, <a href="url">ссылка</a>
- НЕ используй Markdown
- Сохраняй все ссылки из оригинального текста
- Пиши вовлекающий контент для целевой аудитории канала
- Не добавляй хештеги, если их не было в оригинале
- Не добавляй эмодзи чрезмерно"""


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


async def rewrite_post(
    original_text: str,
    agent_instructions: str,
    links_info: str = "",
    model: str = None
) -> Dict[str, Any]:
    """Рерайт поста с сохранением ссылок"""

    prompt = f"Перепиши следующий пост для Telegram-канала, сохрани смысл и стиль:\n\n{original_text}"

    if links_info:
        prompt += f"\n\n⚠️ ОБЯЗАТЕЛЬНО сохрани эти ссылки в тексте:\n{links_info}"

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

    prompt = f"Текущий текст поста:\n\n{current_text}\n\nЗадача: {edit_instruction}"

    return await generate_content(
        user_prompt=prompt,
        agent_instructions=agent_instructions,
        conversation_history=history,
        model=model
    )
