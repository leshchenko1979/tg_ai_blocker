import logging

from aiogram import F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..common.bot import bot
from ..common.mp import mp
from ..common.utils import config
from ..database import get_admin_credits, get_pool, get_referrer
from .dp import dp

logger = logging.getLogger(__name__)

REFERRAL_COMMISSION = config["referral_program"]["rewards"]["commission"]


@dp.message(Command("buy"))
async def handle_buy_command(message: types.Message) -> None:
    """
    Обрабатывает команду покупки звезд
    Показывает меню с разными пакетами звезд
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="100 звезд 💫", callback_data="buy_stars:100"),
                InlineKeyboardButton(text="500 звезд ⭐", callback_data="buy_stars:500"),
            ],
            [
                InlineKeyboardButton(
                    text="1000 звезд 🌟", callback_data="buy_stars:1000"
                ),
                InlineKeyboardButton(
                    text="5000 звезд 🌠", callback_data="buy_stars:5000"
                ),
            ],
        ]
    )

    # Трекинг начала покупки
    mp.track(message.from_user.id, "payment_menu_opened")

    await message.reply(
        "🛒 Выберите количество звезд для покупки:\n\n"
        "• 100 звезд - базовый пакет\n"
        "• 500 звезд - популярный выбор\n"
        "• 1000 звезд - для активных групп\n"
        "• 5000 звезд - максимальная защита\n\n"
        "💡 Чем больше звезд вы покупаете, тем дольше сможете защищать свои группы!\n\n"
        "📢 [Следите за обновлениями в канале проекта](https://t.me/ai_antispam)",
        reply_markup=keyboard,
    )


@dp.callback_query(F.data.startswith("buy_stars:"))
async def handle_buy_stars_callback(callback: types.CallbackQuery):
    """
    Обрабатывает выбор количества звезд для покупки
    """
    await callback.answer()

    stars_amount = int(callback.data.split(":")[1])

    # Трекинг выбора пакета
    mp.track(
        callback.from_user.id,
        "payment_package_selected",
        {"stars_amount": stars_amount},
    )

    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title="Звезды для защиты от спама",
        description=f"Покупка {stars_amount} звезд для защиты ваших групп от спама",
        payload=f"Stars purchase:{stars_amount}",
        provider_token="",
        currency="XTR",
        prices=[types.LabeledPrice(label=f"{stars_amount} звезд", amount=stars_amount)],
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
            await conn.execute(
                "CALL process_successful_payment($1, $2, $3)",
                admin_id,
                stars_amount,
                REFERRAL_COMMISSION / 100,
            )

        # Update Mixpanel profile with new credit balance
        new_balance = await get_admin_credits(admin_id)
        mp.people_set(
            admin_id,
            {
                "credits": new_balance,
                "$last_transaction_amount": stars_amount,
                "$last_transaction_date": str(message.date),
            },
        )

        # Трекинг успешного платежа
        mp.track(admin_id, "payment_successful", {"stars_amount": stars_amount})

        # Проверяем реферальный бонус
        referrer_id = await get_referrer(admin_id)
        if referrer_id:
            commission = int(stars_amount * REFERRAL_COMMISSION / 100)
            # Update referrer's profile
            referrer_balance = await get_admin_credits(referrer_id)
            mp.people_set(
                referrer_id,
                {
                    "credits": referrer_balance,
                    "$last_commission_amount": commission,
                    "$last_commission_date": str(message.date),
                },
            )

            mp.track(
                referrer_id,
                "referral_commission",
                {
                    "referral_id": admin_id,
                    "payment_amount": stars_amount,
                    "commission_amount": commission,
                    "commission_percentage": REFERRAL_COMMISSION,
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
