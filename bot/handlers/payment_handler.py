"""Хэндлер подписки и платежей"""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from database.managers.user_manager import UserManager
from database.managers.payment_manager import PaymentManager
from bot.keyboards.keyboards import subscription_kb, main_menu_kb
from config.settings import config

router = Router()


@router.message(F.text == "💳 Подписка")
async def subscription_menu(message: Message, state: FSMContext):
    await state.clear()
    
    access = await UserManager.get_access_info(message.from_user.id)
    
    # Подписка приоритетнее триала
    if access["subscription_active"]:
        status = f"✅ Подписка активна: {access['subscription_days_left']} дн. осталось"
    elif access["trial_active"]:
        status = f"🎁 Пробный период: {access['trial_days_left']} дн. осталось"
    else:
        status = "❌ Нет активного доступа"
    
    text = (
        f"💳 <b>Подписка и токены</b>\n\n"
        f"<b>Статус:</b> {status}\n"
        f"🪙 <b>Баланс токенов:</b> {access['tokens_balance']:,}\n\n"
        f"<b>Подписка</b> — {config.SUBSCRIPTION_PRICE_RUB}₽/мес\n"
        f"Даёт доступ к генерации контента.\n\n"
        f"<b>Токены</b> — расходуются на каждый запрос к ИИ.\n"
        f"Можно докупить пакетами."
    )
    
    await message.answer(text, reply_markup=subscription_kb(), parse_mode="HTML")


@router.callback_query(F.data == "pay:subscription")
async def pay_subscription(callback: CallbackQuery):
    await callback.answer()
    user = await UserManager.get_by_chat_id(callback.from_user.id)
    if not user:
        return
    
    amount = config.SUBSCRIPTION_PRICE_RUB
    
    payment = await PaymentManager.create_payment(
        user_id=user["id"],
        amount_rub=amount,
        payment_type="subscription",
    )
    
    url = PaymentManager.generate_robokassa_url(
        inv_id=payment["id"],
        amount_rub=amount,
        description="Публикатор ИИ — подписка 1 мес",
    )
    
    await callback.message.answer(
        f"💳 Оплата подписки: <b>{amount}₽</b>\n\n"
        f"<a href='{url}'>Нажмите для оплаты</a>",
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("pay:tokens:"))
async def pay_tokens(callback: CallbackQuery):
    await callback.answer()
    user = await UserManager.get_by_chat_id(callback.from_user.id)
    if not user:
        return
    
    tokens_amount = int(callback.data.split(":")[2])
    amount_rub = config.TOKEN_PACKAGES.get(tokens_amount)
    
    if not amount_rub:
        await callback.message.answer("❌ Неизвестный пакет токенов.")
        return
    
    payment = await PaymentManager.create_payment(
        user_id=user["id"],
        amount_rub=amount_rub,
        payment_type="tokens",
        tokens_amount=tokens_amount,
    )
    
    url = PaymentManager.generate_robokassa_url(
        inv_id=payment["id"],
        amount_rub=amount_rub,
        description=f"Публикатор ИИ — {tokens_amount:,} токенов",
    )
    
    await callback.message.answer(
        f"💳 Оплата токенов: <b>{amount_rub}₽</b> за {tokens_amount:,} токенов\n\n"
        f"<a href='{url}'>Нажмите для оплаты</a>",
        parse_mode="HTML",
    )
