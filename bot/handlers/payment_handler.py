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

    plan = access.get("plan", "free")
    plan_name = access.get("plan_name", "Бесплатный")

    if access.get("subscription_active"):
        status = f"✅ {plan_name} — {access['subscription_days_left']} дн. осталось"
    else:
        status = f"📋 {plan_name}"

    # Информация о лимитах
    posts_limit = access.get("posts_limit")
    posts_used = access.get("posts_used", 0)
    if posts_limit:
        posts_info = f"📝 Постов: {posts_used}/{posts_limit} в этом месяце"
    else:
        posts_info = f"📝 Постов: безлимит"

    text = (
        f"💳 <b>Подписка и тарифы</b>\n\n"
        f"<b>Текущий план:</b> {status}\n"
        f"{posts_info}\n"
        f"🪙 <b>Баланс токенов:</b> {access['tokens_balance']:,}\n\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"📋 <b>Бесплатный</b> — 0₽\n"
        f"• 5 постов в месяц\n"
        f"• Текст + фото\n"
        f"• Водяной знак\n\n"
        f"⭐ <b>Стартер</b> — 100₽/мес\n"
        f"• 15 постов в месяц\n"
        f"• Текст + фото\n"
        f"• Без водяного знака\n\n"
        f"🚀 <b>Про</b> — 300₽/мес\n"
        f"• Безлимит постов\n"
        f"• Текст + фото + видео\n"
        f"• Расписание публикаций\n"
        f"• Аналитика постов\n"
    )

    await message.answer(text, reply_markup=subscription_kb(), parse_mode="HTML")


@router.callback_query(F.data.startswith("pay:plan:"))
async def pay_plan(callback: CallbackQuery):
    """Оплата тарифного плана (starter или pro)"""
    await callback.answer()
    user = await UserManager.get_by_chat_id(callback.from_user.id)
    if not user:
        return

    plan_name = callback.data.split(":")[2]  # "starter" или "pro"
    plan_config = config.PLANS.get(plan_name)

    if not plan_config:
        await callback.message.answer("❌ Неизвестный тариф.")
        return

    amount = plan_config["price_rub"]

    payment = await PaymentManager.create_payment(
        user_id=user["id"],
        amount_rub=amount,
        payment_type="subscription",
        plan=plan_name,
    )

    url = PaymentManager.generate_robokassa_url(
        inv_id=payment["id"],
        amount_rub=amount,
        description=f"Публикатор ИИ — тариф {plan_config['name']} 1 мес",
    )

    await callback.message.answer(
        f"💳 Оплата тарифа <b>{plan_config['name']}</b>: <b>{amount}₽</b>\n\n"
        f"<a href='{url}'>Нажмите для оплаты</a>",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "noop")
async def noop_handler(callback: CallbackQuery):
    await callback.answer()


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
