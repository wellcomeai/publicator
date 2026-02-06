"""Сервис генерации картинок через OpenAI GPT Image API"""

import base64
import tempfile
import os
import structlog
from typing import Optional, Dict, Any
from openai import AsyncOpenAI
from aiogram import Bot
from aiogram.types import FSInputFile
from config.settings import config

logger = structlog.get_logger()

client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)


async def generate_image_prompt(post_text: str) -> str:
    """Сгенерировать промт для картинки на основе текста поста"""
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a creative art director. Generate a short, vivid image description in English (1-2 sentences) suitable for AI image generation. Focus on visual elements, mood, and composition. Do not include any text or lettering in the image description."},
                {"role": "user", "content": f"Describe an image that would fit this post:\n\n{post_text[:500]}"},
            ],
            max_tokens=150,
            temperature=0.8,
        )
        prompt = response.choices[0].message.content.strip()
        logger.info("Image prompt generated", prompt=prompt[:100])
        return prompt
    except Exception as e:
        logger.error("Failed to generate image prompt", error=str(e))
        return "A beautiful professional illustration related to the topic, modern digital art style"


async def generate_image(
    prompt: str,
    bot: Bot,
    chat_id: int,
) -> Optional[Dict[str, Any]]:
    """
    Генерирует картинку через GPT Image API и отправляет в Telegram для получения file_id.

    Возвращает dict с type, file_id, file_unique_id, prompt или None при ошибке.
    """
    temp_path = None
    sent_msg = None
    try:
        response = await client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            size="1536x1024",
            quality="medium",
            n=1,
        )

        image_base64 = response.data[0].b64_json
        image_bytes = base64.b64decode(image_base64)

        # Сохраняем во временный файл
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(image_bytes)
            temp_path = f.name

        # Отправляем в Telegram для получения file_id
        photo = FSInputFile(temp_path)
        sent_msg = await bot.send_photo(chat_id, photo)
        file_id = sent_msg.photo[-1].file_id
        file_unique_id = sent_msg.photo[-1].file_unique_id

        # Удаляем служебное сообщение
        try:
            await bot.delete_message(chat_id, sent_msg.message_id)
        except Exception:
            pass

        logger.info("Image generated", file_id=file_id[:20], prompt=prompt[:80])

        return {
            "type": "photo",
            "file_id": file_id,
            "file_unique_id": file_unique_id,
            "source": "ai_generated",
            "prompt": prompt,
        }

    except Exception as e:
        logger.error("Image generation failed", error=str(e))
        return None

    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception:
                pass
