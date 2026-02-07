"""Сервис генерации контент-плана через GPT"""

import json
import structlog
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from zoneinfo import ZoneInfo
from aiogram import Bot
from aiogram.types import Message

from services import openai_service
from services import image_service
from services.media_manager import PostMediaManager
from database.managers.post_manager import PostManager
from database.managers.user_manager import UserManager
from database.managers.content_queue_manager import ContentQueueManager

logger = structlog.get_logger()


def calculate_posts_count(schedule: dict, days: int = 7) -> int:
    """Сколько постов нужно на N дней по расписанию"""
    slots = schedule.get("slots", [])
    if not slots:
        return 0

    # Считаем уникальные дни
    days_in_schedule = set(s["day"] for s in slots)
    slots_per_day = {}
    for s in slots:
        day = s["day"]
        slots_per_day[day] = slots_per_day.get(day, 0) + 1

    total = sum(slots_per_day.values())
    # total - это за одну неделю; масштабируем на N дней
    weeks = days / 7
    count = max(2, int(total * weeks))
    return count


def calculate_schedule_times(schedule: dict, count: int, start_from: datetime = None) -> List[datetime]:
    """Рассчитать даты публикации для N постов по расписанию"""
    tz_name = schedule.get("timezone", "Europe/Moscow")
    tz = ZoneInfo(tz_name)
    now_local = (start_from or datetime.now(timezone.utc)).astimezone(tz)
    slots = schedule.get("slots", [])

    if not slots:
        return []

    sorted_slots = sorted(slots, key=lambda s: (s["day"], s["time"]))

    result = []
    current_date = now_local.date()
    max_iterations = count * 4  # Safety limit
    iterations = 0

    while len(result) < count and iterations < max_iterations:
        iterations += 1
        for slot in sorted_slots:
            slot_day = slot["day"]
            slot_time = slot["time"]
            h, m = map(int, slot_time.split(":"))

            current_weekday = current_date.weekday()
            days_ahead = (slot_day - current_weekday) % 7

            slot_date = current_date + timedelta(days=days_ahead)
            slot_dt = datetime(slot_date.year, slot_date.month, slot_date.day, h, m, tzinfo=tz)

            if slot_dt <= now_local:
                continue

            # Avoid duplicates
            slot_utc = slot_dt.astimezone(timezone.utc)
            if slot_utc not in result:
                result.append(slot_utc)

            if len(result) >= count:
                break

        current_date += timedelta(weeks=1)

    result.sort()
    return result[:count]


async def generate_topics(
    agent_instructions: str,
    count: int,
    model: str = "gpt-4o-mini",
) -> List[Dict]:
    """Генерация тем через GPT"""
    from openai import AsyncOpenAI
    from config.settings import config

    client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)

    system_prompt = f"""Ты — контент-стратег Telegram-канала.

Инструкции автора канала:
{agent_instructions}

Составь контент-план из {count} тем. Требования:
- Темы разнообразные, но объединённые общей тематикой канала
- Чередуй форматы: обзор, совет, кейс, подборка, мнение
- Каждая тема конкретная, можно сразу писать пост
- Учитывай логическую последовательность
- НЕ нумеруй, НЕ добавляй даты

Ответ СТРОГО в формате JSON массив (без markdown-обёртки):
[
  {{"topic": "конкретная тема поста", "format": "обзор"}},
  {{"topic": "ещё тема", "format": "совет"}}
]

Допустимые форматы: обзор, совет, кейс, подборка, мнение"""

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Сгенерируй {count} тем для контент-плана на 7 дней."},
            ],
            max_tokens=2000,
            temperature=0.8,
        )

        text = response.choices[0].message.content.strip()
        # Remove markdown wrapper if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        topics = json.loads(text)

        input_tokens = response.usage.prompt_tokens if response.usage else 0
        output_tokens = response.usage.completion_tokens if response.usage else 0

        logger.info("📋 Topics generated", count=len(topics),
                     input_tokens=input_tokens, output_tokens=output_tokens)

        return topics, input_tokens + output_tokens

    except Exception as e:
        logger.error("❌ Topic generation failed", error=str(e))
        return [], 0


async def generate_post_for_topic(
    topic: str,
    format: str,
    agent_instructions: str,
    model: str = "gpt-4o-mini",
) -> Dict:
    """Генерация текста одного поста"""
    user_prompt = (
        f"Напиши пост на тему: {topic}\n"
        f"Формат: {format}\n"
        f"ВАЖНО: пост строго до 900 символов."
    )

    result = await openai_service.generate_content(
        user_prompt=user_prompt,
        agent_instructions=agent_instructions,
        model=model,
    )
    return result


async def generate_cover_for_post(
    post_text: str,
    bot: Bot,
    chat_id: int,
) -> Optional[Dict]:
    """Генерация обложки для поста"""
    try:
        prompt = await image_service.generate_image_prompt(post_text)
        image_result = await image_service.generate_image(
            prompt=prompt, bot=bot, chat_id=chat_id
        )
        return image_result
    except Exception as e:
        logger.error("❌ Cover generation failed", error=str(e))
        return None


async def generate_content_plan(
    bot: Bot,
    chat_id: int,
    user_id: int,
    agent_instructions: str,
    agent_model: str,
    schedule: dict,
    generate_covers: bool,
    status_message: Message = None,
) -> List[Dict]:
    """
    Полная генерация контент-плана:
    1. Рассчитать кол-во постов на 7 дней по расписанию
    2. Сгенерировать темы (1 вызов GPT)
    3. Сгенерировать посты по каждой теме
    4. Сгенерировать обложки (если включено)
    5. Сохранить в БД (posts + content_queue)
    """
    # 1. Определяем количество постов
    posts_count = calculate_posts_count(schedule)
    if posts_count == 0:
        return []

    # 2. Рассчитываем даты
    schedule_times = calculate_schedule_times(schedule, posts_count)

    total_tokens_spent = 0

    # 3. Генерируем темы
    if status_message:
        try:
            await status_message.edit_text(
                "⏳ Генерирую контент-план...\n\n"
                f"📝 Темы: ⏳\n"
                f"🖼 Обложки: ожидание"
            )
        except Exception:
            pass

    topics, topic_tokens = await generate_topics(
        agent_instructions=agent_instructions,
        count=posts_count,
        model=agent_model,
    )

    if not topics:
        return []

    total_tokens_spent += topic_tokens
    await UserManager.spend_tokens(chat_id, topic_tokens)

    # 4. Генерируем посты по каждой теме
    queue_items = []
    covers_done = 0
    for i, topic_item in enumerate(topics):
        topic = topic_item.get("topic", "")
        fmt = topic_item.get("format", "обзор")

        # Update progress before generating each post
        if status_message:
            try:
                covers_status = f"{covers_done}/{len(topics)} ⏳" if generate_covers else "выкл"
                await status_message.edit_text(
                    "⏳ Генерирую контент-план...\n\n"
                    f"📝 Посты: {i}/{len(topics)} ⏳\n"
                    f"🖼 Обложки: {covers_status}"
                )
            except Exception:
                pass

        # Generate post text
        result = await generate_post_for_topic(
            topic=topic,
            format=fmt,
            agent_instructions=agent_instructions,
            model=agent_model,
        )

        if not result.get("success"):
            logger.error("❌ Post generation failed for topic", topic=topic[:50])
            continue

        post_text = result["text"]
        post_tokens = result.get("total_tokens", 0)
        total_tokens_spent += post_tokens
        await UserManager.spend_tokens(chat_id, post_tokens)

        # Create post record
        post = await PostManager.create_post(
            user_id=user_id,
            generated_text=post_text,
            original_text=topic,
            input_tokens=result.get("input_tokens", 0),
            output_tokens=result.get("output_tokens", 0),
        )
        post_id = post["id"]

        # Generate cover if enabled
        if generate_covers:
            if status_message:
                try:
                    await status_message.edit_text(
                        "⏳ Генерирую контент-план...\n\n"
                        f"📝 Посты: {i + 1}/{len(topics)} ✅\n"
                        f"🖼 Обложки: {covers_done}/{len(topics)} ⏳"
                    )
                except Exception:
                    pass

            cover = await generate_cover_for_post(post_text, bot, chat_id)
            if cover:
                await PostMediaManager.add_media_item(post_id, cover)
                covers_done += 1

        scheduled_at = schedule_times[i] if i < len(schedule_times) else None

        queue_items.append({
            "topic": topic,
            "format": fmt,
            "post_id": post_id,
            "scheduled_at": scheduled_at,
            "status": "ready",
        })

    # 5. Save to content_queue
    if queue_items:
        saved = await ContentQueueManager.add_items_batch(user_id, queue_items)
        logger.info("✅ Content plan generated",
                     user_id=user_id, posts=len(saved),
                     tokens_spent=total_tokens_spent)
        return saved

    return []
