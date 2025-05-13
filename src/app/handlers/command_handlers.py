import logging
from typing import cast

from aiogram import F, types
from aiogram.filters import Command

from ..common.mp import mp
from ..common.utils import config, sanitize_markdown
from ..database import (
    INITIAL_CREDITS,
    get_admin_credits,
    get_admin_groups,
    get_spam_deletion_state,
    get_spent_credits_last_week,
    initialize_new_admin,
    toggle_spam_deletion,
)
from .dp import dp

logger = logging.getLogger(__name__)


@dp.message(Command("start", "help"), F.chat.type == "private")
async def handle_help_command(message: types.Message) -> str:
    """
    Обработчик команд /start и /help
    Отправляет пользователю справочную информацию и начисляет начальные звезды новым пользователям
    """
    if not message.from_user:
        return "command_no_user_info"

    if not message.text:
        return "command_no_text"

    user = cast(types.User, message.from_user)  # Cast to ensure proper type hints
    user_id = user.id

    # Добавляем трекинг
    mp.track(
        user_id,
        "command_start",
        {
            "user_id": user_id,
            "chat_type": message.chat.type,
            "command": message.text.split()[0],
            "is_help": message.text.startswith("/help"),
            "user_language": user.language_code,
            "platform": user.is_premium,  # as proxy for platform capabilities
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
                "📢 Подпишись на [канал проекта](https://t.me/ai_antispam), чтобы быть в курсе обновлений!\n\n"
            )
        else:
            welcome_text = ""
    else:
        welcome_text = ""

    # Формируем и очищаем текст
    full_text = welcome_text + config["help_text"]
    safe_text = sanitize_markdown(full_text)

    # Максимальная длина сообщения в Telegram
    MAX_LEN = 4096

    # Отправляем текст, разбивая на части только если он слишком длинный
    for i in range(0, len(safe_text), MAX_LEN):
        await message.reply(
            safe_text[i : i + MAX_LEN],
            parse_mode="markdown",
            disable_web_page_preview=True,
        )

    return (
        "command_help_sent"
        if message.text.startswith("/help")
        else "command_start_completed"
    )


@dp.message(Command("stats"))
async def handle_stats_command(message: types.Message) -> str:
    """
    Обработчик команды /stats
    Показывает баланс пользователя и статус модерации в его группах
    """
    if not message.from_user:
        return "command_no_user_info"

    user = cast(types.User, message.from_user)  # Cast to ensure proper type hints
    user_id = user.id

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
        return "command_stats_sent"

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
        return "command_stats_error"


@dp.message(Command("mode"))
async def handle_mode_command(message: types.Message) -> str:
    """
    Обработчик команды /mode
    Переключает режим между удалением спама и уведомлениями
    """
    if not message.from_user:
        return "command_no_user_info"

    user = cast(types.User, message.from_user)  # Cast to ensure proper type hints
    user_id = user.id

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
        return (
            "command_mode_changed_to_deletion"
            if delete_spam
            else "command_mode_changed_to_notification"
        )

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
        return "command_mode_error"


@dp.message(Command("ref"), F.chat.type == "private")
async def cmd_ref(message: types.Message):
    """Объясняет, как получить официальную реферальную ссылку Telegram Partner Program"""
    await message.answer(
        "<b>Как получить свою реферальную ссылку для этого бота:</b>\n\n"
        "1. Откройте профиль этого бота в Telegram.\n"
        "2. Нажмите <b>Заработать звёзды</b>.\n"
        "3. Найдите этот бот в списке программ и нажмите <b>Присоединиться к программе</b>.\n"
        "4. После этого появится ваша персональная реферальная ссылка — её можно скопировать и отправить друзьям.\n\n"
        "<i>Подробнее: https://telegram.org/tour/affiliate-programs/</i>",
        parse_mode="HTML",
    )
