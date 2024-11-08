from aiogram import F, types
from aiogram.filters import Command

from common.bot import bot
from common.database import add_credits, get_user_groups, set_group_moderation
from common.dp import dp
from common.yandex_logging import get_yandex_logger, log_function_call

logger = get_yandex_logger(__name__)

STARS_AMOUNT = 100  # Количество звезд за одну покупку


@dp.message(Command("buy"))
@log_function_call(logger)
async def handle_buy_command(message: types.Message) -> None:
    """
    Обрабатывает команду покупки звезд
    """
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
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@dp.message(F.successful_payment)
async def process_successful_payment(message: types.Message):
    """Обработчик успешного платежа"""
    user_id = message.from_user.id
    stars_amount = message.successful_payment.total_amount

    # Начисляем звезды
    await add_credits(user_id, stars_amount)

    # Включаем модерацию во всех группах пользователя
    user_groups = await get_user_groups(user_id)
    for group_id in user_groups:
        await set_group_moderation(group_id, True)

    await bot.send_message(
        user_id,
        f"🎉 Поздравляю, человек! Я начислил тебе {stars_amount} звезд и активировал "
        f"защиту в твоих группах.\n\n"
        "Теперь я буду охранять твое киберпространство с утроенной силой! 💪",
    )
