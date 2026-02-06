"""Сервис транскрипции голосовых сообщений через OpenAI Whisper"""

import tempfile
import os
import structlog
from typing import Optional
from aiogram import Bot
from openai import AsyncOpenAI
from config.settings import config

logger = structlog.get_logger()

client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)


async def transcribe_voice(bot: Bot, voice) -> Optional[str]:
    """
    Транскрипция голосового сообщения через OpenAI Whisper API.
    
    1. Скачиваем voice файл во временный файл
    2. Отправляем в Whisper API
    3. Получаем текст
    4. Удаляем временный файл
    
    Возвращает текст или None при ошибке.
    """
    temp_path = None
    try:
        # Скачиваем голосовое сообщение
        file_info = await bot.get_file(voice.file_id)

        temp_file = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
        temp_path = temp_file.name
        temp_file.close()

        await bot.download_file(file_info.file_path, temp_path)

        logger.info("🎤 Voice file downloaded",
                     file_id=voice.file_id,
                     duration=getattr(voice, "duration", 0),
                     file_size=getattr(voice, "file_size", 0))

        # Транскрибируем через Whisper
        with open(temp_path, "rb") as audio_file:
            response = await client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ru",
            )

        text = response.text.strip()

        if not text:
            logger.warning("⚠️ Whisper returned empty text", file_id=voice.file_id)
            return None

        logger.info("✅ Voice transcribed",
                     length=len(text),
                     preview=text[:80])

        return text

    except Exception as e:
        logger.error("❌ Voice transcription failed", error=str(e))
        return None

    finally:
        # Удаляем временный файл
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception:
                pass
