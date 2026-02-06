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
    SUBSCRIPTION_PRICE_RUB = int(os.getenv("SUBSCRIPTION_PRICE_RUB", "300"))
    DEFAULT_TOKEN_LIMIT = int(os.getenv("DEFAULT_TOKEN_LIMIT", "100000"))

    # Token packages (tokens: price_rub)
    TOKEN_PACKAGES = {
        50000: 100,
        150000: 250,
        500000: 700,
    }


config = Config()
