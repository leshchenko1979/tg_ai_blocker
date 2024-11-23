import urllib.parse

from aiogram import F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..common.mp import mp
from ..common.utils import config
from ..common.yandex_logging import get_yandex_logger, log_function_call
from ..database.referral_operations import get_referrals, get_total_earnings
from .dp import dp

logger = get_yandex_logger(__name__)

SHARE_MESSAGE = """
🤖 Познакомься с моим цифровым защитником!

Это бот с ИИ, который охраняет Telegram-группы от спама. Он:

• Мгновенно определяет спамеров с помощью нейросети
• Автоматически удаляет нежелательные сообщения
• Ведет белый список проверенных пользователей
• Учится на примерах и становится умнее

Я уже использую его и очень доволен! Попробуй и ты 👇
"""


@dp.message(Command("ref"), F.chat.type == "private")
@log_function_call(logger)
async def cmd_ref(message: types.Message):
    """Генерирует реферальную ссылку и кнопку для шаринга"""
    user_id = message.from_user.id

    try:
        bot = await message.bot.get_me()
        ref_link = f"https://t.me/{bot.username}?start=ref{user_id}"

        # Encode the message for the share URL
        encoded_message = urllib.parse.quote(SHARE_MESSAGE)
        encoded_link = urllib.parse.quote(ref_link)

        # Create keyboard with properly encoded URLs
        builder = InlineKeyboardBuilder()
        builder.button(
            text="📢 Поделиться с другом",
            url=f"https://t.me/share/url?url={encoded_link}&text={encoded_message}",
        )

        commission = config["referral_program"]["rewards"]["commission"]

        # Трекинг генерации реферальной ссылки
        mp.track(user_id, "referral_link_generated")

        await message.answer(
            "🔗 Вот ваша реферальная ссылка:\n\n"
            f"`{ref_link}`\n\n"
            f"Отправьте её друзьям и получайте {commission}% от их покупок в виде звёзд!\n\n"
            "💡 Готовое сообщение для друга:\n\n"
            f"{SHARE_MESSAGE}",
            parse_mode="Markdown",
            reply_markup=builder.as_markup(),
        )
    except Exception as e:
        logger.error(f"Error generating referral link: {e}", exc_info=True)
        mp.track(user_id, "error_ref_command", {"error": str(e)})
        await message.answer("Произошла ошибка при генерации реферальной ссылки.")


@dp.message(Command("refs"), F.chat.type == "private")
@log_function_call(logger)
async def cmd_refs(message: types.Message):
    """Показывает статистику по рефералам"""
    user_id = message.from_user.id

    try:
        referrals = await get_referrals(user_id)
        total_earned = await get_total_earnings(user_id)

        # Трекинг просмотра статистики
        mp.track(
            user_id,
            "referral_stats_viewed",
            {"referrals_count": len(referrals), "total_earned": total_earned},
        )

        if not referrals:
            await message.answer(
                "У вас пока нет рефералов. Отправьте друзьям свою реферальную "
                "ссылку командой /ref"
            )
            return

        text = [
            f"👥 Ваши рефералы: {len(referrals)} чел.",
            f"💰 Всего заработано звезд: {total_earned}",
            "\n\nПоследние рефералы:",
        ]

        for ref in referrals[:5]:
            joined = ref["joined_at"].strftime("%d.%m.%Y")
            text.append(f"• {joined}: заработано {ref['earned_stars']} звезд")

        text.append("\nПолучите свою реферальную ссылку командой /ref")

        await message.answer("\n".join(text))

    except Exception as e:
        logger.error(f"Error showing referral stats: {e}", exc_info=True)
        mp.track(user_id, "error_refs_command", {"error": str(e)})
        await message.answer("Произошла ошибка при получении статистики рефералов.")
