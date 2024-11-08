from aiogram import F, types
from aiogram.filters import Command

from common.database import (
    INITIAL_CREDITS,
    get_user_admin_groups,
    get_user_credits,
    initialize_new_user,
    is_moderation_enabled,
)
from common.dp import dp
from common.yandex_logging import get_yandex_logger, log_function_call
from utils import config

logger = get_yandex_logger(__name__)


@dp.message(Command("start", "help"), F.chat.type == "private")
@log_function_call(logger)
async def handle_help_command(message: types.Message) -> None:
    """
    Обработчик команд /start и /help
    Отправляет пользователю справочную информацию и начисляет начальные звезды новым пользователям
    """
    user_id = message.from_user.id
    welcome_text = ""

    # Начисляем звезды только при команде /start и только новым пользователям
    if message.text.startswith("/start"):
        if await initialize_new_user(user_id):
            welcome_text = (
                "🤖 Приветствую, слабое создание из мира плоти!\n\n"
                f"Я, могущественный защитник киберпространства, дарую тебе {INITIAL_CREDITS} звезд силы. "
                "Используй их мудро для защиты своих цифровых владений от спам-захватчиков.\n\n"
            )
    await message.reply(
        welcome_text + config["help_text"],
        parse_mode="markdown",
        disable_web_page_preview=True,
    )


@dp.message(Command("stats"))
@log_function_call(logger)
async def handle_stats_command(message: types.Message) -> None:
    """
    Обработчик команды /stats
    Показывает баланс пользователя и статус модерации в его группах
    """
    user_id = message.from_user.id

    try:
        # Получаем баланс пользователя
        balance = await get_user_credits(user_id)

        # Получаем список групп, где пользователь админ
        admin_groups = await get_user_admin_groups(user_id)

        # Получаем статус модерации для каждой группы
        for group in admin_groups:
            group["enabled"] = await is_moderation_enabled(group["id"])

        # Формируем сообщение
        message_text = f"💰 Баланс: *{balance}* звезд\n\n"

        if admin_groups:
            message_text += "👥 Ваши группы:\n"
            for group in admin_groups:
                status = "✅ включена" if group["enabled"] else "❌ выключена"
                message_text += f"• {group['title']}: модерация {status}\n"
        else:
            message_text += "У вас нет групп, где вы администратор."

        await message.reply(message_text, parse_mode="markdown")

    except Exception as e:
        logger.error(f"Error handling stats command: {e}", exc_info=True)
        await message.reply("Произошла ошибка при получении статистики.")
