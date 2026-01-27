import logging

from aiogram import F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..common.bot import bot
from ..common.mp import mp
from ..common.utils import retry_on_network_error
from ..database import get_admin_credits, get_pool
from .dp import dp

logger = logging.getLogger(__name__)


@dp.message(Command("buy"), F.chat.type == "private")
async def handle_buy_command(message: types.Message) -> str:
    """
    Обрабатывает команду покупки звезд
    Показывает меню с разными пакетами звезд
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="100 звезд 💫", callback_data="buy_stars:100"
                ),
                InlineKeyboardButton(
                    text="500 звезд ⭐", callback_data="buy_stars:500"
                ),
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
    if message.from_user:
        mp.track(message.from_user.id, "payment_menu_opened")

    await message.reply(
        "🛒 Выберите количество звезд для покупки:\n\n"
        "• 100 звезд - базовый пакет\n"
        "• 500 звезд - популярный выбор\n"
        "• 1000 звезд - для активных групп\n"
        "• 5000 звезд - максимальная защита\n\n"
        "💡 Чем больше звезд вы покупаете, тем дольше сможете защищать свои группы!\n\n"
        '📢 <a href="https://t.me/ai_antispam">Следите за обновлениями в канале проекта</a>',
        reply_markup=keyboard,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    return "command_buy_menu_shown"


@dp.callback_query(F.data.startswith("buy_stars:"))
async def handle_buy_stars_callback(callback: types.CallbackQuery) -> str:
    """
    Обрабатывает выбор количества звезд для покупки
    """
    await callback.answer()

    if not callback.data or ":" not in callback.data:
        if callback.message:
            await callback.message.reply("❌ Ошибка: некорректные данные платежа")
        return "invalid_callback_data"

    stars_amount = int(callback.data.split(":")[1])

    # Трекинг выбора пакета
    if callback.from_user:
        mp.track(
            callback.from_user.id,
            "payment_package_selected",
            {"stars_amount": stars_amount},
        )

    if (
        not callback.message
        or not hasattr(callback.message, "chat")
        or not callback.message.chat
    ):
        if callback.message:
            await callback.message.reply("❌ Ошибка: невозможно отправить счет")
        return "invalid_message"

    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title="Звезды для защиты от спама",
        description=f"Покупка {stars_amount} звезд для защиты ваших групп от спама",
        payload=f"Stars purchase:{stars_amount}",
        provider_token="",
        currency="XTR",
        prices=[types.LabeledPrice(label=f"{stars_amount} звезд", amount=stars_amount)],
    )
    return "callback_buy_stars_selected"


@dp.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: types.PreCheckoutQuery) -> str:
    """Обработчик предварительной проверки платежа"""
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
    return "pre_checkout_processed"


@dp.message(F.successful_payment)
async def process_successful_payment(message: types.Message) -> str:
    """Обработчик успешного платежа"""
    if not message.from_user or not message.successful_payment:
        logger.warning(
            "Received successful payment message with missing user or payment data"
        )
        return "payment_processing_skipped"

    admin_id = message.from_user.id
    stars_amount = message.successful_payment.total_amount

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "CALL process_successful_payment($1, $2)",
                admin_id,
                stars_amount,
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

        @retry_on_network_error
        async def send_payment_confirmation():
            return await bot.send_message(
                admin_id,
                f"🎉 Поздравляю, человек! Я начислил тебе {stars_amount} звезд и активировал "
                f"защиту в твоих группах.\n\n"
                "Теперь я буду охранять твое киберпространство с утроенной силой! 💪",
                parse_mode="HTML",
            )

        await send_payment_confirmation()
        return "payment_successful_processed"

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
