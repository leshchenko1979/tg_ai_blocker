from aiogram import F, types
from aiogram.filters import Command

from common.bot import bot
from common.database import add_credits, get_admin_groups, set_group_moderation
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

    # Трекинг начала покупки
    mp.track(
        message.from_user.id, "payment_buy_initiated", {"stars_amount": STARS_AMOUNT}
    )

    await bot.send_invoice(
        chat_id=message.chat.id,
        title="Звезды для защиты от спама",
        description=f"Покупка {STARS_AMOUNT} звезд для защиты ваших групп от спама",
        payload="Stars purchase",
        provider_token="",
        currency="XTR",
        prices=[types.LabeledPrice(label=f"{STARS_AMOUNT} звезд", amount=STARS_AMOUNT)],
    )


@dp.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: types.PreCheckoutQuery):
    """Обработчик предварительной проверки платежа"""
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@dp.message(F.successful_payment)
async def process_successful_payment(message: types.Message):
    """Обработчик успешного платежа"""
    admin_id = message.from_user.id
    stars_amount = message.successful_payment.total_amount

    try:
        # Начисляем звезды
        await add_credits(admin_id, stars_amount)

        # Трекинг успешного платежа
        mp.track(admin_id, "payment_successful", {"stars_amount": stars_amount})

        await bot.send_message(
            admin_id,
            f"🎉 Поздравляю, человек! Я начислил тебе {stars_amount} звезд и активировал "
            f"защиту в твоих группах.\n\n"
            "Теперь я буду охранять твое киберпространство с утроенной силой! 💪",
        )

    except Exception as e:
        # Трекинг ошибок
        mp.track(
            admin_id,
            "error_payment",
            {
                "error_type": type(e).__name__,
                "error_message": str(e),
                "stars_amount": stars_amount,
                "payment_info": str(message.successful_payment),
            },
        )
        logger.error(f"Error processing payment: {e}", exc_info=True)
        raise
