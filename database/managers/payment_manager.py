"""Менеджер платежей (Robokassa)"""

import hashlib
import structlog
from typing import Optional, Dict, Any
from database.db import get_pool
from config.settings import config

logger = structlog.get_logger()


class PaymentManager:

    @staticmethod
    async def create_payment(user_id: int, amount_rub: int, payment_type: str, tokens_amount: int = 0) -> Dict[str, Any]:
        """Создать запись о платеже"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO payments (user_id, amount_rub, payment_type, tokens_amount)
                VALUES ($1, $2, $3, $4)
                RETURNING *
            """, user_id, amount_rub, payment_type, tokens_amount)
            logger.info("💰 Payment created", user_id=user_id, amount=amount_rub, type=payment_type)
            return dict(row)

    @staticmethod
    async def confirm_payment(inv_id: int, robokassa_data: dict = None) -> Optional[Dict[str, Any]]:
        """Подтвердить платёж"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                UPDATE payments SET status = 'success', robokassa_data = $2, updated_at = NOW()
                WHERE id = $1 AND status = 'pending'
                RETURNING *
            """, inv_id, robokassa_data)
            if row:
                logger.info("✅ Payment confirmed", inv_id=inv_id)
                return dict(row)
            return None

    @staticmethod
    async def get_payment(payment_id: int) -> Optional[Dict[str, Any]]:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM payments WHERE id = $1", payment_id)
            return dict(row) if row else None

    @staticmethod
    def generate_robokassa_url(inv_id: int, amount_rub: int, description: str) -> str:
        """Генерация URL для оплаты через Robokassa"""
        login = config.ROBOKASSA_LOGIN
        password1 = config.ROBOKASSA_PASSWORD1
        is_test = config.ROBOKASSA_TEST_MODE

        # Формируем подпись: login:amount:inv_id:password1
        signature_str = f"{login}:{amount_rub}:{inv_id}:{password1}"
        signature = hashlib.md5(signature_str.encode()).hexdigest()

        base_url = "https://auth.robokassa.ru/Merchant/Index.aspx"
        params = (
            f"MerchantLogin={login}"
            f"&OutSum={amount_rub}"
            f"&InvId={inv_id}"
            f"&Description={description}"
            f"&SignatureValue={signature}"
            f"&Culture=ru"
        )
        if is_test:
            params += "&IsTest=1"

        return f"{base_url}?{params}"

    @staticmethod
    def verify_robokassa_signature(out_sum: str, inv_id: str, signature: str, password2: str = None) -> bool:
        """Проверка подписи от Robokassa (Result URL)"""
        pwd = password2 or config.ROBOKASSA_PASSWORD2
        expected = hashlib.md5(f"{out_sum}:{inv_id}:{pwd}".encode()).hexdigest().upper()
        return signature.upper() == expected
