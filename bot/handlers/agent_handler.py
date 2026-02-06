"""Хэндлер ИИ-агента"""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from database.managers.user_manager import UserManager
from database.managers.agent_manager import AgentManager
from bot.states.states import AgentSetup
from bot.keyboards.keyboards import agent_menu_kb, agent_confirm_delete_kb, main_menu_kb, cancel_kb

router = Router()


# ===== КНОПКА «МОЙ АГЕНТ» =====

@router.message(F.text == "🤖 Мой агент")
async def my_agent(message: Message, state: FSMContext):
    await state.clear()
    user = await UserManager.get_by_chat_id(message.from_user.id)
    if not user:
        await message.answer("Сначала нажмите /start")
        return
    
    has_agent = await AgentManager.has_agent(user["id"])
    
    if has_agent:
        agent = await AgentManager.get_agent(user["id"])
        text = (
            f"🤖 <b>{agent['agent_name']}</b>\n\n"
            f"📝 <b>Промт:</b>\n<i>{agent['instructions'][:300]}{'...' if len(agent['instructions']) > 300 else ''}</i>\n\n"
            f"🧠 Модель: {agent['model']}"
        )
    else:
        text = (
            "🤖 У вас ещё нет ИИ-агента.\n\n"
            "Агент определяет стиль и тему генерируемого контента.\n"
            "Создайте агента, чтобы начать!"
        )
    
    await message.answer(text, reply_markup=agent_menu_kb(has_agent), parse_mode="HTML")


# ===== СОЗДАНИЕ АГЕНТА =====

@router.callback_query(F.data == "agent:create")
async def agent_create_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AgentSetup.waiting_name)
    await callback.message.answer(
        "✏️ Введите <b>название</b> агента (например: «Крипто-канал», «Кулинарный блог»):",
        parse_mode="HTML",
        reply_markup=cancel_kb()
    )


@router.message(AgentSetup.waiting_name)
async def agent_name_received(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2 or len(name) > 100:
        await message.answer("❌ Название должно быть от 2 до 100 символов. Попробуйте ещё раз:")
        return
    
    await state.update_data(agent_name=name)
    await state.set_state(AgentSetup.waiting_instructions)
    
    await message.answer(
        f"✅ Название: <b>{name}</b>\n\n"
        f"Теперь введите <b>промт</b> — инструкции для ИИ.\n\n"
        f"Опишите:\n"
        f"• Тему и стиль канала\n"
        f"• Целевую аудиторию\n"
        f"• Тон общения (формальный/дружеский)\n"
        f"• Любые особенности (эмодзи, длина, структура)\n\n"
        f"<i>Пример: \"Пиши посты для крипто-канала, аудитория — трейдеры 25-40 лет. "
        f"Стиль: дружеский но экспертный. Используй эмодзи умеренно. "
        f"Каждый пост должен быть 200-400 слов.\"</i>",
        parse_mode="HTML"
    )


@router.message(AgentSetup.waiting_instructions)
async def agent_instructions_received(message: Message, state: FSMContext):
    instructions = message.text.strip()
    if len(instructions) < 10:
        await message.answer("❌ Промт слишком короткий (минимум 10 символов). Попробуйте ещё раз:")
        return
    if len(instructions) > 2000:
        await message.answer(f"❌ Промт слишком длинный ({len(instructions)}/2000). Сократите и попробуйте ещё раз:")
        return
    
    data = await state.get_data()
    agent_name = data["agent_name"]
    
    user = await UserManager.get_by_chat_id(message.from_user.id)
    agent = await AgentManager.create_or_update(
        user_id=user["id"],
        agent_name=agent_name,
        instructions=instructions,
    )
    
    await state.clear()
    
    await message.answer(
        f"✅ Агент <b>{agent['agent_name']}</b> создан!\n\n"
        f"Теперь привяжите канал (📢 Мой канал) и начинайте создавать контент.",
        reply_markup=main_menu_kb(),
        parse_mode="HTML"
    )


# ===== РЕДАКТИРОВАНИЕ ПРОМТА =====

@router.callback_query(F.data == "agent:edit")
async def agent_edit_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AgentSetup.waiting_instructions)
    
    user = await UserManager.get_by_chat_id(callback.from_user.id)
    agent = await AgentManager.get_agent(user["id"])
    
    # Сохраняем имя для обновления
    await state.update_data(agent_name=agent["agent_name"])
    
    await callback.message.answer(
        f"✏️ Текущий промт:\n<i>{agent['instructions'][:500]}</i>\n\n"
        f"Введите новый промт:",
        parse_mode="HTML"
    )


# ===== ИНФОРМАЦИЯ =====

@router.callback_query(F.data == "agent:info")
async def agent_info(callback: CallbackQuery):
    await callback.answer()
    user = await UserManager.get_by_chat_id(callback.from_user.id)
    agent = await AgentManager.get_agent(user["id"])
    
    if not agent:
        await callback.message.answer("Агент не найден.")
        return
    
    text = (
        f"🤖 <b>{agent['agent_name']}</b>\n\n"
        f"📝 <b>Промт:</b>\n{agent['instructions']}\n\n"
        f"🧠 Модель: {agent['model']}\n"
        f"📅 Создан: {agent['created_at'].strftime('%d.%m.%Y %H:%M')}"
    )
    await callback.message.answer(text, parse_mode="HTML")


# ===== УДАЛЕНИЕ =====

@router.callback_query(F.data == "agent:delete")
async def agent_delete_ask(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "⚠️ Вы уверены что хотите удалить агента?\nВсе настройки будут потеряны.",
        reply_markup=agent_confirm_delete_kb()
    )


@router.callback_query(F.data == "agent:confirm_delete")
async def agent_confirm_delete(callback: CallbackQuery):
    await callback.answer()
    user = await UserManager.get_by_chat_id(callback.from_user.id)
    await AgentManager.delete_agent(user["id"])
    await callback.message.answer("✅ Агент удалён.", reply_markup=main_menu_kb())


@router.callback_query(F.data == "agent:cancel_delete")
async def agent_cancel_delete(callback: CallbackQuery):
    await callback.answer("Отменено")
    await callback.message.delete()
