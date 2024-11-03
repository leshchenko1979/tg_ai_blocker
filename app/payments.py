import os
from datetime import datetime, timedelta
from typing import Optional

from aiogram.filters import Command
from aiogram import types

from yookassa import Configuration, Payment
from yookassa.domain.common.confirmation_type import ConfirmationType
from yookassa.domain.request.payment_request import PaymentRequest

from common.database_upstash import add_credits, get_user_groups, set_group_moderation
from common.yandex_logging import get_yandex_logger, log_function_call
from common.bot import bot
from common.dp import dp


logger = get_yandex_logger(__name__)

# Инициализация YooKassa
Configuration.configure(os.getenv("YOOKASSA_SHOP_ID"), os.getenv("YOOKASSA_SECRET_KEY"))

CREDITS_PRICE = 1000  # Цена за 1000 кредитов в рублях
CREDITS_AMOUNT = 1000  # Количество кредитов за одну покупку


@log_function_call(logger)
async def create_payment(user_id: int, username: Optional[str] = None) -> Optional[str]:
    """
    Создает платеж в YooKassa и возвращает URL для оплаты

    Args:
        user_id: ID пользователя
        username: Имя пользователя (опционально)

    Returns:
        str: URL для оплаты или None в случае ошибки
    """
    try:
        payment = Payment.create(
            PaymentRequest(
                {
                    "amount": {"value": str(CREDITS_PRICE), "currency": "RUB"},
                    "confirmation": {
                        "type": ConfirmationType.REDIRECT,
                        "return_url": "https://t.me/ai_spam_blocker_bot",
                    },
                    "capture": True,
                    "description": f"Покупка {CREDITS_AMOUNT} кредитов для защиты от спама",
                    "metadata": {
                        "user_id": user_id,
                        "username": username or "",
                        "credits_amount": CREDITS_AMOUNT,
                    },
                    "expires_at": (datetime.now() + timedelta(days=1)).isoformat(),
                }
            )
        )

        return payment.confirmation.confirmation_url

    except Exception as e:
        logger.error(f"Ошибка при создании платежа: {e}")
        return None


@log_function_call(logger)
async def process_payment(payment_data: dict) -> None:
    """
    Обрабатывает уведомление о платеже от YooKassa

    Args:
        payment_data: Данные платежа от YooKassa
    """
    try:
        if payment_data["event"] == "payment.succeeded":
            payment = payment_data["object"]
            metadata = payment["metadata"]

            user_id = int(metadata["user_id"])
            credits_amount = int(metadata["credits_amount"])

            # Начисляем кредиты
            await add_credits(user_id, credits_amount)

            # Включаем модерацию во всех группах пользователя
            user_groups = await get_user_groups(user_id)
            for group_id in user_groups:
                await set_group_moderation(group_id, True)

            # Уведомляем пользователя
            await bot.send_message(
                user_id,
                f"🎉 Поздравляю, человек! Твой платеж на {payment['amount']['value']} "
                f"{payment['amount']['currency']} успешно обработан.\n\n"
                f"Я начислил тебе {credits_amount} кредитов и активировал "
                f"защиту в твоих группах.\n\n"
                "Теперь я буду охранять твое киберпространство с утроенной силой! 💪",
            )

    except Exception as e:
        logger.error(f"Ошибка при обработке платежа: {e}")
        raise


@dp.message(Command("buy"))
@log_function_call(logger)
async def handle_buy_command(message: types.Message) -> None:
    """
    Обрабатывает команду покупки кредитов
    """

    user_id = message.from_user.id
    username = message.from_user.username

    # Создаем платеж
    payment_url = await create_payment(user_id, username)

    if payment_url:
        await bot.send_message(
            user_id,
            "🛡 Приветствую, человек!\n\n"
            f"Я готов усилить защиту твоего киберпространства за {CREDITS_PRICE} RUB.\n"
            f"За это ты получишь {CREDITS_AMOUNT} кредитов.\n\n"
            "Нажми кнопку ниже, чтобы провести оплату. У тебя есть 24 часа.\n\n"
            "Как только платеж будет обработан, я сразу же приступлю к работе! 🤖",
            reply_markup={
                "inline_keyboard": [[{"text": "Оплатить", "url": payment_url}]]
            },
        )
    else:
        await bot.send_message(
            user_id,
            "❌ Произошла ошибка при создании платежа. Попробуй позже или обратись к "
            "моему создателю @leshchenko1979.",
        )


import hmac
import base64
from hashlib import sha256


def verify_yookassa_signature(body: bytes, signature: str, secret_key: str) -> bool:
    """
    Проверяет подпись уведомления от YooKassa

    Args:
        body: Тело запроса в байтах
        signature: Подпись из заголовка X-Request-Signature
        secret_key: Секретный ключ из личного кабинета YooKassa

    Returns:
        bool: True если подпись верна
    """
    try:
        secret_key_bytes = secret_key.encode("utf-8")
        signature_bytes = base64.b64decode(signature)

        calculated_hash = hmac.new(secret_key_bytes, body, sha256).digest()

        return hmac.compare_digest(calculated_hash, signature_bytes)
    except Exception as e:
        logger.error(f"Ошибка при проверке подписи: {e}")
        return False
