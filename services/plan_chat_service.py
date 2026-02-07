"""
Сервис диалога с ИИ для согласования контент-плана.
Оркестрирует: OpenAI API <-> PlanChatManager <-> Handler.
"""

import json
import structlog
from typing import Optional, Dict, Any, Tuple
from openai import AsyncOpenAI

from config.settings import config
from database.managers.plan_chat_manager import PlanChatManager
from database.managers.user_manager import UserManager
from services.openai_service import CONFIRM_PLAN_TOOL, build_plan_system_prompt

logger = structlog.get_logger()

client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)


class PlanChatService:
    """
    Основной сервис для ведения диалога по контент-плану.

    Возвращает tuple:
        (reply_text, confirmed_plan)
        - reply_text: str — текст ответа ИИ для отправки пользователю
        - confirmed_plan: Optional[dict] — если ИИ вызвал confirm, тут план; иначе None
    """

    @staticmethod
    async def start_session(
        chat_id: int,
        user_id: int,
        agent_instructions: str,
        channel_name: str,
        slots_count: int,
        schedule_info: str,
        current_date: str = "",
        user_topics: str = ""
    ) -> Tuple[str, int]:
        """
        Начать новую сессию диалога.

        Returns:
            (first_ai_message, session_id)
        """
        # Создаём сессию в БД
        session = await PlanChatManager.create_session(user_id)
        session_id = session["id"]

        # Формируем системный промт
        system_prompt = build_plan_system_prompt(
            agent_instructions=agent_instructions,
            channel_name=channel_name,
            slots_count=slots_count,
            schedule_info=schedule_info,
            current_date=current_date,
            user_topics=user_topics
        )

        # Сохраняем system message
        await PlanChatManager.append_message(session_id, "system", system_prompt)

        # Первый запрос к ИИ — пусть предложит план
        first_user_message = "Предложи контент-план"
        if user_topics:
            first_user_message = f"Предложи контент-план. Я хочу осветить эти темы: {user_topics}"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": first_user_message}
        ]
        await PlanChatManager.append_message(session_id, "user", first_user_message)

        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            tools=[CONFIRM_PLAN_TOOL],
            temperature=0.8,
        )

        reply = response.choices[0].message.content or ""
        await PlanChatManager.append_message(session_id, "assistant", reply)

        # Списываем токены
        total_tokens = response.usage.total_tokens if response.usage else 0
        if total_tokens > 0:
            await UserManager.spend_tokens(chat_id, total_tokens)

        logger.info("Plan chat started",
                     session_id=session_id,
                     user_id=user_id,
                     tokens=total_tokens)

        return reply, session_id

    @staticmethod
    async def send_message(
        session_id: int,
        user_message: str,
        chat_id: int
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Отправить сообщение пользователя в диалог.

        Returns:
            (reply_text, confirmed_plan_or_none)
        """
        # Сохраняем сообщение пользователя
        await PlanChatManager.append_message(session_id, "user", user_message)

        # Достаём всю историю
        messages = await PlanChatManager.get_messages(session_id)

        # Запрос к OpenAI с function calling
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            tools=[CONFIRM_PLAN_TOOL],
            temperature=0.7,
        )

        msg = response.choices[0].message
        total_tokens = response.usage.total_tokens if response.usage else 0

        # Списываем токены
        if total_tokens > 0:
            await UserManager.spend_tokens(chat_id, total_tokens)

        # === ПЕРЕХВАТ FUNCTION CALL ===
        if msg.tool_calls:
            tool_call = msg.tool_calls[0]

            if tool_call.function.name == "confirm_content_plan":
                try:
                    args = json.loads(tool_call.function.arguments)
                    topics = args.get("topics", [])

                    if not topics:
                        error_reply = "Произошла ошибка. Давайте ещё раз сформулируем план."
                        await PlanChatManager.append_message(session_id, "assistant", error_reply)
                        return error_reply, None

                    confirmed_plan = {"topics": topics}

                    # Подтверждаем сессию
                    await PlanChatManager.confirm_session(session_id, confirmed_plan)

                    logger.info("Content plan confirmed via function call",
                                session_id=session_id,
                                topics_count=len(topics),
                                tokens=total_tokens)

                    # Формируем текст подтверждения
                    plan_lines = []
                    for i, t in enumerate(topics, 1):
                        plan_lines.append(
                            f"{i}. {t['topic']} ({t['format']})\n"
                            f"   {t.get('description', '')}"
                        )
                    plan_text = "\n\n".join(plan_lines)

                    return plan_text, confirmed_plan

                except json.JSONDecodeError as e:
                    logger.error("Failed to parse confirm args", error=str(e))
                    error_reply = "Произошла ошибка при подтверждении. Попробуйте ещё раз сказать 'подтверждаю'."
                    await PlanChatManager.append_message(session_id, "assistant", error_reply)
                    return error_reply, None

        # === ОБЫЧНЫЙ ТЕКСТОВЫЙ ОТВЕТ ===
        reply = msg.content or "..."
        await PlanChatManager.append_message(session_id, "assistant", reply)

        logger.info("Plan chat message processed",
                     session_id=session_id,
                     tokens=total_tokens)

        return reply, None

    @staticmethod
    async def cancel(session_id: int) -> None:
        """Отменить текущую сессию"""
        await PlanChatManager.cancel_session(session_id)
