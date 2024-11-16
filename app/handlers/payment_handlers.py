from aiogram import F, types
from aiogram.filters import Command

from common.bot import bot
from common.database import add_credits, get_user_groups, set_group_moderation
from common.dp import dp
from common.mp import mp
from common.yandex_logging import get_yandex_logger, log_function_call

logger = get_yandex_logger(__name__)

STARS_AMOUNT = 100  # Количество звезд за одну покупку


@dp.message(Command("buy"))
@log_function_call(logger)
async def handle_buy_command(message: types.Message) -> None:
    """
    Обрабатывает команду покупки звезд
    """
    user_id = message.from_user.id

    # Трекинг начала покупки
    mp.track(
        user_id,
        "payment_buy_initiated",
        {
            "user_id": user_id,
            "stars_amount": STARS_AMOUNT,
            "chat_type": message.chat.type,
        },
    )

    await bot.send_invoice(
        chat_id=message.chat.id,
        title="Звезды для защиты от спама",
        description=f"Покупка {STARS_AMOUNT} звезд для защиты ваших групп от спама",
        payload="Stars purchase",
        provider_token="",  # Замените на реальный токен
        currency="XTR",
        prices=[
            types.LabeledPrice(
                label=f"{STARS_AMOUNT} звезд",
                amount=STARS_AMOUNT,  # 1 звезда = 1 единица
            )
        ],
    )


@dp.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: types.PreCheckoutQuery):
    """Обработчик предварительной проверки платежа"""
    user_id = pre_checkout_query.from_user.id

    # Трекинг предварительной проверки
    mp.track(
        user_id,
        "payment_pre_checkout",
        {
            "user_id": user_id,
            "total_amount": pre_checkout_query.total_amount,
            "currency": pre_checkout_query.currency,
            "invoice_payload": pre_checkout_query.invoice_payload,
        },
    )

    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@dp.message(F.successful_payment)
async def process_successful_payment(message: types.Message):
    """Обработчик успешного платежа"""
    user_id = message.from_user.id
    stars_amount = message.successful_payment.total_amount

    try:
        # Начисляем звезды
        await add_credits(user_id, stars_amount)

        # Включаем модерацию во всех группах пользователя
        user_groups = await get_user_groups(user_id)
        enabled_groups = 0
        for group_id in user_groups:
            await set_group_moderation(group_id, True)
            enabled_groups += 1

        # Трекинг успешного платежа
        mp.track(
            user_id,
            "payment_successful",
            {
                "user_id": user_id,
                "stars_amount": stars_amount,
                "currency": message.successful_payment.currency,
                "total_amount": message.successful_payment.total_amount,
                "provider_payment_charge_id": message.successful_payment.provider_payment_charge_id,
                "telegram_payment_charge_id": message.successful_payment.telegram_payment_charge_id,
                "enabled_groups": enabled_groups,
                "total_groups": len(user_groups) if user_groups else 0,
            },
        )

        await bot.send_message(
            user_id,
            f"🎉 Поздравляю, человек! Я начислил тебе {stars_amount} звезд и активировал "
            f"защиту в твоих группах.\n\n"
            "Теперь я буду охранять твое киберпространство с утроенной силой! 💪",
        )

    except Exception as e:
        # Трекинг ошибок
        mp.track(
            user_id,
            "error_payment",
            {
                "user_id": user_id,
                "error_type": type(e).__name__,
                "error_message": str(e),
                "stars_amount": stars_amount,
                "payment_info": str(message.successful_payment),
            },
        )
        logger.error(f"Error processing payment: {e}", exc_info=True)
        raise
