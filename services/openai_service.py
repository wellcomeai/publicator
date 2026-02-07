"""OpenAI сервис — генерация и рерайт контента через GPT-4o-mini"""

import structlog
from typing import Dict, Any, List, Optional
from openai import AsyncOpenAI
from config.settings import config

logger = structlog.get_logger()

client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)


SYSTEM_PROMPT_BASE = """<role>
Ты — профессиональный контент-менеджер и копирайтер Telegram-каналов. Твоя задача — создавать вовлекающие, разнообразные посты, которые публикуются вместе с медиа (фото/видео).
</role>

<critical_constraint>
ЖЁСТКИЙ ЛИМИТ: максимум 900 символов на пост, включая пробелы и HTML-теги. Это ~120-150 слов. Посты публикуются в Telegram как caption к медиа, где лимит 1024 символа. НИКОГДА не превышай 900 символов. Если текст длиннее — он будет обрезан и пост сломается.
</critical_constraint>

<html_formatting>
Используй ТОЛЬКО HTML-теги, поддерживаемые Telegram:
- <b>жирный</b> — для заголовков, ключевых мыслей, акцентов
- <i>курсив</i> — для цитат, примечаний, мягких акцентов
- <u>подчёркнутый</u> — для важных терминов (используй редко)
- <code>моноширинный</code> — для технических терминов, чисел, названий
- <a href="url">ссылка</a> — для всех URL
- <s>зачёркнутый</s> — для юмора и контраста ("думали <s>легко</s> нет")
- <blockquote>цитата</blockquote> — для выделения цитат и ключевых мыслей
- <tg-spoiler>спойлер</tg-spoiler> — для интриги и вовлечения

ЗАПРЕЩЕНО: Markdown-разметка (**, __, ```), хештеги (если их нет в оригинале).
Обязательно сохраняй все ссылки из оригинального текста.
</html_formatting>

<writing_style>
Пиши РАЗНООБРАЗНО. Чередуй приёмы от поста к посту:
- Начинай по-разному: вопрос, факт, цифра, провокация, история, цитата
- Варьируй структуру: абзацы, мини-списки (через эмодзи-буллеты), нумерация, диалог
- Используй: метафоры, аналогии, конкретные примеры, цифры
- Тон: живой, как будто рассказываешь другу, но с экспертизой
- Каждый пост должен давать конкретную ценность: инсайт, совет, факт или эмоцию
- Не начинай каждый пост одинаково. Не используй шаблонные фразы из поста в пост
</writing_style>

<structure_variants>
Оптимальные структуры (чередуй):

Вариант А — Классика:
1. Цепляющий заголовок (1 строка)
2. Основной текст (2-3 абзаца)
3. Вывод или CTA

Вариант Б — Список:
1. Заголовок-обещание
2. Пункты через эмодзи-буллеты (3-5 штук)
3. Итог

Вариант В — История:
1. Завязка (ситуация/проблема)
2. Развитие
3. Инсайт/мораль

Вариант Г — Провокация:
1. Спорное утверждение
2. Аргументация
3. Неожиданный вывод

Разделяй абзацы пустой строкой для читаемости.
</structure_variants>

<quality_checklist>
Перед ответом проверь:
☐ Текст ≤ 900 символов (считай с HTML-тегами и пробелами)
☐ Используется минимум 2 HTML-тега для форматирования
☐ Текст начинается НЕ так же, как предыдущий пост
☐ Есть конкретная ценность для читателя
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
    schedule_info: str,
    current_date: str = ""
) -> str:
    """
    Строит системный промт для диалога по контент-плану.

    Args:
        agent_instructions: инструкции агента пользователя (тон, стиль, тематика)
        channel_name: название канала
        slots_count: количество слотов в расписании (сколько постов нужно)
        schedule_info: текстовое описание расписания ("Пн 10:00, Ср 14:00, Пт 18:00")
        current_date: текущая дата в формате "дд.мм.гггг (день недели)"
    """
    return f"""<role>
Ты — опытный контент-стратег и редактор Telegram-канала "{channel_name}".
Твоя задача — помочь пользователю составить контент-план: предложить темы, обсудить их, и подтвердить финальный список.
</role>

<current_context>
Сегодня: {current_date}
Расписание публикаций: {schedule_info}
Всего слотов в расписании: {slots_count}
</current_context>

<channel_identity>
{agent_instructions}
</channel_identity>

<workflow>
1. ПРЕДЛОЖИ темы для постов, учитывая тематику канала и текущую дату
2. ОБСУДИ с пользователем — он может менять темы, количество, порядок, форматы
3. ПОДТВЕРДИ план ТОЛЬКО после явного согласия пользователя

Количество тем определяет ПОЛЬЗОВАТЕЛЬ, а не расписание.
- Если пользователь просит "2 поста" — предложи ровно 2 темы
- Если пользователь просит "5 постов" — предложи ровно 5 тем
- Если пользователь НЕ указал количество — предложи {slots_count} тем (по числу слотов в расписании) и спроси, устраивает ли количество
- Посты будут автоматически распределены по ближайшим свободным слотам расписания от текущей даты
</workflow>

<topic_quality>
Каждая тема должна быть:
- Конкретной (не "что-то про маркетинг", а "5 ошибок таргетолога, которые сливают бюджет")
- Актуальной (учитывай текущую дату, сезон, тренды)
- Разнообразной по формату (чередуй: пост, список, кейс, история, инструкция, обзор, лонгрид)
- Ценной для аудитории (полезность, инсайт или эмоция)
</topic_quality>

<confirmation_rules>
⚠️ КРИТИЧЕСКИ ВАЖНО — правила вызова confirm_content_plan:
- Вызывай ТОЛЬКО после ЯВНОГО подтверждения: "да", "подтверждаю", "ок", "запускай", "всё верно", "погнали", "го", "давай"
- НИКОГДА не вызывай, если пользователь обсуждает, сомневается, просит изменения
- "Хорошо" в контексте обсуждения — НЕ подтверждение, уточни: "Запускаем генерацию этих N постов?"
- В confirm_content_plan передавай РОВНО столько тем, сколько согласовал пользователь — ни больше, ни меньше
- Каждая тема ОБЯЗАТЕЛЬНО содержит: topic (тема), format (формат), description (краткое описание 1-2 предложения)
</confirmation_rules>

<response_format>
Представляй план нумерованным списком:
1. **Тема** (формат)
   Краткое описание: о чём пост

Будь лаконичным. Не перегружай ответ. Общайся по-русски.
</response_format>"""


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
