"""Сервис генерации видео через OpenAI Sora API"""

import asyncio
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

# Таймаут ожидания генерации видео (5 минут)
VIDEO_GENERATION_TIMEOUT = 300
# Интервал поллинга статуса
POLL_INTERVAL = 5


async def generate_video_prompt(post_text: str) -> str:
    """Сгенерировать промт для видео на основе текста поста"""
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a creative video director. Generate a short, vivid video scene description in English (1-2 sentences) suitable for AI video generation. Focus on motion, action, and visual storytelling. Keep it simple and achievable."},
                {"role": "user", "content": f"Describe a short video clip that would fit this post:\n\n{post_text[:500]}"},
            ],
            max_tokens=150,
            temperature=0.8,
        )
        prompt = response.choices[0].message.content.strip()
        logger.info("Video prompt generated", prompt=prompt[:100])
        return prompt
    except Exception as e:
        logger.error("Failed to generate video prompt", error=str(e))
        return "A smooth cinematic scene related to the topic, professional quality"


async def generate_video(
    prompt: str,
    bot: Bot,
    chat_id: int,
    duration: int = 4,
    status_message=None,
) -> Optional[Dict[str, Any]]:
    """
    Генерирует видео через Sora API, скачивает и отправляет в Telegram.

    duration: 4, 8 или 12 секунд
    status_message: сообщение для обновления прогресса

    Возвращает dict с type, file_id, file_unique_id, prompt, duration или None при ошибке.
    """
    temp_path = None
    try:
        # 1. Создаём задачу на генерацию
        if status_message:
            try:
                await status_message.edit_text("🎬 Создаю видео... Отправлено на генерацию.")
            except Exception:
                pass

        response = await client.videos.create(
            model="sora-2",
            prompt=prompt,
            duration=duration,
            resolution="720p",
        )

        video_id = response.id
        logger.info("Video generation started", video_id=video_id, duration=duration)

        # 2. Поллим статус
        elapsed = 0
        while elapsed < VIDEO_GENERATION_TIMEOUT:
            video = await client.videos.retrieve(video_id)

            if video.status == "completed":
                if status_message:
                    try:
                        await status_message.edit_text("🎬 Видео готово! Загружаю...")
                    except Exception:
                        pass
                break
            elif video.status == "failed":
                error_msg = getattr(video, "error", "Unknown error")
                logger.error("Video generation failed", video_id=video_id, error=error_msg)
                return None

            # Обновляем статус
            if status_message and elapsed % 15 == 0:
                progress = min(int(elapsed / VIDEO_GENERATION_TIMEOUT * 100), 95)
                try:
                    await status_message.edit_text(
                        f"🎬 Генерирую видео... {progress}%\n"
                        f"<i>Статус: {video.status}</i>",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
        else:
            logger.error("Video generation timed out", video_id=video_id)
            return None

        # 3. Скачиваем видео
        content_response = await client.videos.content(video_id)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(content_response)
            temp_path = f.name

        # 4. Отправляем в Telegram для получения file_id
        video_file = FSInputFile(temp_path)
        sent_msg = await bot.send_video(chat_id, video_file)
        file_id = sent_msg.video.file_id
        file_unique_id = sent_msg.video.file_unique_id

        # Удаляем служебное сообщение
        try:
            await bot.delete_message(chat_id, sent_msg.message_id)
        except Exception:
            pass

        logger.info("Video generated", file_id=file_id[:20], duration=duration)

        return {
            "type": "video",
            "file_id": file_id,
            "file_unique_id": file_unique_id,
            "source": "ai_generated",
            "prompt": prompt,
            "duration": duration,
        }

    except Exception as e:
        logger.error("Video generation failed", error=str(e))
        return None

    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception:
                pass
