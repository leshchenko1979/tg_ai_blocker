from aiogram import F, types
from aiogram.filters import Command
from common.bot import bot
from common.database import get_pool, get_referrer
from common.dp import dp
from common.mp import mp
from common.yandex_logging import get_yandex_logger, log_function_call
from utils import config

logger = get_yandex_logger(__name__)

STARS_AMOUNT = 100  # Количество звезд за одну покупку
REFERRAL_COMMISSION = (
    config["referral_program"]["rewards"]["commission"] / 100
)  # Конвертируем проценты в долю


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
        pool = await get_pool()
        async with pool.acquire() as conn:
            # Выполняем всю логику в одной процедуре
            await conn.execute(
                "CALL process_successful_payment($1, $2, $3)",
                admin_id,
                stars_amount,
                REFERRAL_COMMISSION,
            )

        # Трекинг успешного платежа
        mp.track(admin_id, "payment_successful", {"stars_amount": stars_amount})

        # Проверяем был ли начислен реферальный бонус
        referrer_id = await get_referrer(admin_id)
        if referrer_id:
            commission = int(stars_amount * REFERRAL_COMMISSION)
            # Трекинг реферальной комиссии
            mp.track(
                referrer_id,
                "referral_commission",
                {
                    "referral_id": admin_id,
                    "payment_amount": stars_amount,
                    "commission_amount": commission,
                    "commission_percentage": config["referral_program"]["rewards"][
                        "commission"
                    ],
                },
            )

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
