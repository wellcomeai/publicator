"""
Публикатор ИИ — главный модуль приложения.
FastAPI + aiogram webhook + Robokassa callbacks
"""

import asyncio
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
from utils.album_buffer import add_to_buffer, flush_buffer, store_album, ALBUM_WAIT_SECONDS

# Handlers
from bot.handlers import (
    start_handler,
    onboarding_handler,
    agent_handler,
    channel_handler,
    media_handler,
    content_handler,
    profile_handler,
    payment_handler,
    schedule_handler,
    watcher_handler,
)
from services.scheduler_service import run_scheduler
from services.watcher_scheduler import run_watcher, watcher_status, CHECK_INTERVAL_SECONDS
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
dp.include_router(onboarding_handler.router)  # До agent_handler — перехватывает Onboarding states
dp.include_router(agent_handler.router)
dp.include_router(channel_handler.router)
dp.include_router(media_handler.router)      # До content_handler — обрабатывает MediaManagement states
dp.include_router(content_handler.router)
dp.include_router(schedule_handler.router)
dp.include_router(watcher_handler.router)
dp.include_router(profile_handler.router)
dp.include_router(payment_handler.router)

# Album middleware — достаёт собранный альбом из буфера
content_handler.router.message.middleware(AlbumMiddleware())


# ===== ALBUM PROCESSING =====

async def _process_album_delayed(media_group_id: str):
    """
    Фоновая задача: ждёт сбора всех сообщений альбома,
    затем подаёт первый update в dispatcher с собранным альбомом в буфере.
    """
    await asyncio.sleep(ALBUM_WAIT_SECONDS)

    messages = flush_buffer(media_group_id)
    if not messages:
        return

    # Сохраняем собранный альбом — middleware заберёт его
    store_album(media_group_id, messages)

    # Подаём первое сообщение как update в dispatcher
    first_message = messages[0]
    fake_update = Update(update_id=0, message=first_message)

    try:
        await dp.feed_update(bot, fake_update)
    except Exception as e:
        logger.error("❌ Album processing failed",
                     media_group_id=media_group_id,
                     error=str(e))


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

    # Запуск фонового планировщика отложенных постов
    scheduler_task = asyncio.create_task(run_scheduler(bot))
    watcher_task = asyncio.create_task(run_watcher(bot))

    yield

    # Shutdown
    scheduler_task.cancel()
    watcher_task.cancel()
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

    # === БУФЕРИЗАЦИЯ АЛЬБОМОВ ===
    # Если сообщение — часть медиагруппы, буферизуем его и сразу возвращаем 200.
    # Обработка произойдёт через фоновую задачу после сбора всех элементов.
    if update.message and update.message.media_group_id:
        group_id = update.message.media_group_id
        is_first = add_to_buffer(group_id, update.message)

        if is_first:
            # Запускаем отложенную обработку (только для первого сообщения группы)
            asyncio.create_task(_process_album_delayed(group_id))

        # Мгновенный ответ Telegram — не блокируем webhook
        return Response(status_code=200)

    # Обычные сообщения — обрабатываем как раньше
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
        plan = payment.get("plan") or "pro"
        await UserManager.activate_subscription(chat_id, plan=plan)
        plan_config = config.PLANS.get(plan, {})
        plan_name = plan_config.get("name", plan)
        try:
            await bot.send_message(chat_id, f"✅ Подписка «{plan_name}» активирована на 30 дней! 🎉")
        except Exception:
            pass
        logger.info("✅ Subscription activated via payment", chat_id=chat_id, plan=plan)

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


# ===== WATCHER STATUS =====

@app.get("/watcher/status")
async def get_watcher_status():
    return {
        "last_run_at": watcher_status.last_run_at.isoformat() if watcher_status.last_run_at else None,
        "last_run_duration_sec": watcher_status.last_run_duration_sec,
        "cycles_count": watcher_status.cycles_count,
        "channels_checked": watcher_status.total_channels_checked,
        "new_posts_found": watcher_status.total_new_posts_found,
        "posts_sent": watcher_status.total_posts_sent,
        "errors": watcher_status.errors,
        "channels_detail": watcher_status.channels_detail,
        "interval_sec": CHECK_INTERVAL_SECONDS,
    }


# ===== HEALTHCHECK =====

@app.get("/health")
async def health():
    return {"status": "ok", "service": "publicator-ai"}
