"""
Публикатор ИИ — главный модуль приложения.
FastAPI + aiogram webhook + Robokassa callbacks
"""

import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties

from config.settings import config
from database.db import init_db, close_db
from database.managers.user_manager import UserManager
from database.managers.payment_manager import PaymentManager

# Handlers
from bot.handlers import (
    start_handler,
    agent_handler,
    channel_handler,
    content_handler,
    profile_handler,
    payment_handler,
)
from bot.middlewares import AlbumMiddleware

logger = structlog.get_logger()

# ===== BOT & DISPATCHER =====

bot = Bot(
    token=config.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML"),
)

dp = Dispatcher(storage=MemoryStorage())

# Register routers
dp.include_router(start_handler.router)
dp.include_router(agent_handler.router)
dp.include_router(channel_handler.router)
dp.include_router(content_handler.router)
dp.include_router(profile_handler.router)
dp.include_router(payment_handler.router)

# Album middleware — собирает медиагруппы в один батч
content_handler.router.message.middleware(AlbumMiddleware())


# ===== FASTAPI LIFESPAN =====

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 Starting Публикатор ИИ...")
    await init_db()

    webhook_url = f"{config.APP_URL}{config.WEBHOOK_PATH}"
    await bot.set_webhook(
        url=webhook_url,
        secret_token=config.WEBHOOK_SECRET,
        drop_pending_updates=True,
    )
    logger.info("✅ Webhook set", url=webhook_url)

    yield

    # Shutdown
    await bot.delete_webhook()
    await close_db()
    await bot.session.close()
    logger.info("👋 Shutdown complete")


app = FastAPI(title="Публикатор ИИ", lifespan=lifespan)


# ===== WEBHOOK ENDPOINT =====

@app.post(config.WEBHOOK_PATH)
async def webhook(request: Request):
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret != config.WEBHOOK_SECRET:
        return Response(status_code=403)

    data = await request.json()
    update = Update(**data)
    await dp.feed_update(bot, update)
    return Response(status_code=200)


# ===== ROBOKASSA RESULT URL (серверное подтверждение) =====

@app.get("/robokassa/result")
@app.post("/robokassa/result")
async def robokassa_result(request: Request):
    """Robokassa Result URL — серверное подтверждение оплаты"""
    if request.method == "POST":
        data = await request.form()
        params = dict(data)
    else:
        params = dict(request.query_params)

    out_sum = params.get("OutSum", "")
    inv_id = params.get("InvId", "")
    signature = params.get("SignatureValue", "")

    logger.info("💰 Robokassa result", inv_id=inv_id, out_sum=out_sum)

    # Проверяем подпись
    if not PaymentManager.verify_robokassa_signature(out_sum, inv_id, signature):
        logger.error("❌ Invalid Robokassa signature", inv_id=inv_id)
        return Response(content="bad sign", status_code=400)

    # Подтверждаем платёж
    payment = await PaymentManager.confirm_payment(
        inv_id=int(inv_id),
        robokassa_data=params,
    )

    if not payment:
        logger.error("❌ Payment not found or already confirmed", inv_id=inv_id)
        return Response(content=f"OK{inv_id}", status_code=200)

    # Получаем user_id из платежа
    from database.db import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", payment["user_id"])

    if not user:
        logger.error("❌ User not found for payment", user_id=payment["user_id"])
        return Response(content=f"OK{inv_id}", status_code=200)

    chat_id = user["chat_id"]

    # Обрабатываем тип платежа
    if payment["payment_type"] == "subscription":
        await UserManager.activate_subscription(chat_id)
        try:
            await bot.send_message(chat_id, "✅ Подписка активирована на 30 дней! 🎉")
        except Exception:
            pass
        logger.info("✅ Subscription activated via payment", chat_id=chat_id)

    elif payment["payment_type"] == "tokens":
        tokens = payment["tokens_amount"]
        await UserManager.add_tokens(chat_id, tokens)
        try:
            await bot.send_message(chat_id, f"✅ Добавлено {tokens:,} токенов! 🪙")
        except Exception:
            pass
        logger.info("✅ Tokens added via payment", chat_id=chat_id, tokens=tokens)

    return Response(content=f"OK{inv_id}", status_code=200)


# ===== ROBOKASSA SUCCESS / FAIL URLs (для пользователя) =====

@app.get("/robokassa/success")
async def robokassa_success(request: Request):
    return Response(content="<h1>✅ Оплата прошла успешно!</h1><p>Вернитесь в бота.</p>", media_type="text/html")


@app.get("/robokassa/fail")
async def robokassa_fail(request: Request):
    return Response(content="<h1>❌ Оплата отменена</h1><p>Вернитесь в бота и попробуйте снова.</p>", media_type="text/html")


# ===== HEALTHCHECK =====

@app.get("/health")
async def health():
    return {"status": "ok", "service": "publicator-ai"}
