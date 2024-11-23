from aiogram import F, types
from aiogram.filters import Command

from ..common.mp import mp
from ..common.utils import config
from ..common.yandex_logging import get_yandex_logger, log_function_call
from ..database import (
    INITIAL_CREDITS,
    get_admin_credits,
    get_admin_groups,
    get_spam_deletion_state,
    get_spent_credits_last_week,
    initialize_new_admin,
    save_referral,
    toggle_spam_deletion,
)
from .dp import dp

logger = get_yandex_logger(__name__)


@dp.message(Command("start", "help"), F.chat.type == "private")
@log_function_call(logger)
async def handle_help_command(message: types.Message) -> None:
    """
    Обработчик команд /start и /help
    Отправляет пользователю справочную информацию и начисляет начальные звезды новым пользователям
    """
    user_id = message.from_user.id

    # Проверяем реферальный код
    if message.text.startswith("/start ref"):
        try:
            referrer_id = int(message.text[10:])  # Обрезаем "/start ref"
        except ValueError:
            logger.warning(f"Invalid referral code: {message.text[10:]}")
            return

        if await save_referral(user_id, referrer_id):
            # Трекинг нового реферала
            mp.track(
                referrer_id,
                "referral_joined",
                {"referral_id": user_id, "ref_link": message.text},
            )
        else:
            logger.warning(
                f"Referral link already exists or referral chain is cyclic: {message.text[10:]}"
            )

    # Добавляем трекинг
    mp.track(
        user_id,
        "command_start",
        {
            "user_id": user_id,
            "chat_type": message.chat.type,
            "command": message.text.split()[0],
            "is_help": message.text.startswith("/help"),
            "user_language": message.from_user.language_code,
            "platform": message.from_user.is_premium,  # as proxy for platform capabilities
        },
    )

    # Начисляем звезды только при команде /start и только новым пользователям
    if message.text.startswith("/start"):
        is_new = await initialize_new_admin(user_id)
        # Трекинг нового пользователя
        if is_new:
            mp.track(
                user_id,
                "command_start_new_user",
                {"user_id": user_id, "initial_credits": INITIAL_CREDITS},
            )
            welcome_text = (
                "🤖 Приветствую, слабое создание из мира плоти!\n\n"
                f"Я, могущественный защитник киберпространства, дарую тебе {INITIAL_CREDITS} звезд силы. "
                "Используй их мудро для защиты своих цифровых владений от спам-захватчиков.\n\n"
            )
        else:
            welcome_text = ""
    else:
        welcome_text = ""

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
        balance = await get_admin_credits(user_id)

        # Получаем потраченные звезды за неделю
        spent_week = await get_spent_credits_last_week(user_id)

        # Получаем список групп с их статусами модерации
        admin_groups = await get_admin_groups(user_id)

        # Формируем сообщение
        message_text = (
            f"💰 Баланс: *{balance}* звезд\n"
            f"📊 Потрачено за последние 7 дней: *{spent_week}* звезд\n\n"
        )

        if admin_groups:
            message_text += "👥 Ваши группы:\n"
            for group in admin_groups:
                status = (
                    "✅ включена" if group["is_moderation_enabled"] else "❌ выключена"
                )
                message_text += f"• {group['title']}: модерация {status}\n"
        else:
            message_text += "У вас нет групп, где вы администратор."

        # Добавляем информацию о режиме работы
        delete_spam = await get_spam_deletion_state(user_id)
        mode = "🗑 Режим удаления" if delete_spam else "🔔 Режим уведомлений"
        message_text += f"\n\nТекущий режим: *{mode}*"

        # Трекинг просмотра статистики
        mp.track(
            user_id,
            "command_stats",
            {
                "user_id": user_id,
                "balance": balance,
                "spent_week": spent_week,
                "groups_count": len(admin_groups) if admin_groups else 0,
                "deletion_mode": delete_spam,
                "chat_type": message.chat.type,
            },
        )

        await message.reply(message_text, parse_mode="markdown")

    except Exception as e:
        # Трекинг ошибок
        mp.track(
            user_id,
            "error_stats",
            {
                "user_id": user_id,
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        logger.error(f"Error handling stats command: {e}", exc_info=True)
        await message.reply("Произошла ошибка при получении статистики.")


@dp.message(Command("mode"))
@log_function_call(logger)
async def handle_mode_command(message: types.Message) -> None:
    """
    Обработчик команды /mode
    Переключает режим между удалением спама и уведомлениями
    """
    user_id = message.from_user.id

    try:
        # Переключаем режим
        delete_spam = await toggle_spam_deletion(user_id)

        # Трекинг изменения режима
        mp.track(
            user_id,
            "command_mode_toggle",
            {
                "user_id": user_id,
                "new_mode": "deletion" if delete_spam else "notification",
                "chat_type": message.chat.type,
            },
        )

        # Формируем сообщение о новом режиме
        if delete_spam:
            message_text = (
                "🗑 Включен *режим удаления*\n\n"
                "Теперь я буду автоматически удалять сообщения, "
                "определённые как спам, в ваших группах."
            )
        else:
            message_text = (
                "🔔 Включен *режим уведомлений*\n\n"
                "Теперь я буду только уведомлять о сообщениях, "
                "определённых как спам, но не буду их удалять."
            )

        await message.reply(message_text, parse_mode="markdown")

    except Exception as e:
        # Трекинг ошибок
        mp.track(
            user_id,
            "error_mode",
            {
                "user_id": user_id,
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        logger.error(f"Error handling mode command: {e}", exc_info=True)
        await message.reply("Произошла ошибка при изменении режима работы.")
