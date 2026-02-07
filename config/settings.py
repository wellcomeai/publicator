"""Конфигурация приложения"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Bot
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    BOT_USERNAME = os.getenv("BOT_USERNAME", "publicator_ai_bot")

    # Database
    DATABASE_URL = os.getenv("DATABASE_URL", "")

    # OpenAI
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL = "gpt-4o-mini"

    # Robokassa
    ROBOKASSA_LOGIN = os.getenv("ROBOKASSA_LOGIN", "")
    ROBOKASSA_PASSWORD1 = os.getenv("ROBOKASSA_PASSWORD1", "")
    ROBOKASSA_PASSWORD2 = os.getenv("ROBOKASSA_PASSWORD2", "")
    ROBOKASSA_TEST_MODE = os.getenv("ROBOKASSA_TEST_MODE", "true").lower() == "true"

    # Webhook
    APP_URL = os.getenv("APP_URL", "")
    WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
    WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "supersecret")

    # Settings
    TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "3"))
    SUBSCRIPTION_PRICE_RUB = int(os.getenv("SUBSCRIPTION_PRICE_RUB", "10"))
    DEFAULT_TOKEN_LIMIT = int(os.getenv("DEFAULT_TOKEN_LIMIT", "100000"))

    # Token packages (tokens: price_rub)
    TOKEN_PACKAGES = {
        50000: 100,
        150000: 250,
        500000: 700,
    }

    # Plans
    PLANS = {
        "free": {
            "name": "Бесплатный",
            "price_rub": 0,
            "posts_per_month": 5,
            "allow_photo": True,
            "allow_video": False,
            "allow_schedule": False,
            "allow_analytics": False,
            "watermark": True,
            "watch_channels": 0,
        },
        "starter": {
            "name": "Стартер",
            "price_rub": 100,
            "posts_per_month": 15,
            "allow_photo": True,
            "allow_video": False,
            "allow_schedule": False,
            "allow_analytics": False,
            "watermark": False,
            "watch_channels": 1,
        },
        "pro": {
            "name": "Про",
            "price_rub": 300,
            "posts_per_month": None,  # безлимит
            "allow_photo": True,
            "allow_video": True,
            "allow_schedule": True,
            "allow_analytics": True,
            "watermark": False,
            "watch_channels": 3,
        },
    }


config = Config()
