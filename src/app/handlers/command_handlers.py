import logging
from typing import cast

from aiogram import F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..common.mp import mp
from ..common.utils import get_affiliate_url, sanitize_html
from ..database import (
    INITIAL_CREDITS,
    get_admin_credits,
    get_admin_stats,
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

    command = message.text.split()[0]

    # Загружаем конфигурацию
    from ..common.utils import load_config

    config = load_config()

    # Добавляем трекинг
    mp.track(
        user_id,
        f"command_{command.lstrip('/')}",
        {
            "user_id": user_id,
            "chat_type": message.chat.type,
            "command": command,
            "user_language": user.language_code,
            "platform": user.is_premium,
        },
    )

    # Логика для /start
    if command == "/start":
        is_new = await initialize_new_admin(user_id)
        if is_new:
            mp.track(
                user_id,
                "command_start_new_user",
                {"user_id": user_id, "initial_credits": INITIAL_CREDITS},
            )
            welcome_text = config.get("start_welcome_text", "Добро пожаловать!")
            await message.reply(
                welcome_text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return "command_start_new_user_sent"
        # Для существующих пользователей покажем приветствие с быстрым доступом к функциям
        existing_user_text = config.get("start_existing_user_text", "С возвращением!")
        await message.reply(
            existing_user_text,
            parse_mode="HTML",
        )
        return "command_start_existing_user"

    # Логика для /help
    # config["help_text"] contains safe HTML that we control, no need to sanitize
    safe_text = config["help_text"]

    # Создаем клавиатуру с кнопками для разных разделов помощи
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 Как начать", callback_data="help_getting_started"
                ),
                InlineKeyboardButton(
                    text="📚 Обучение бота", callback_data="help_training"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⚙️ Что проверяется", callback_data="help_moderation"
                ),
                InlineKeyboardButton(text="💡 Команды", callback_data="help_commands"),
            ],
            [
                InlineKeyboardButton(text="💰 Оплата", callback_data="help_payment"),
                InlineKeyboardButton(text="🔧 Поддержка", callback_data="help_support"),
            ],
        ]
    )

    await message.reply(
        safe_text,
        parse_mode="HTML",
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )

    return "command_help_sent"


@dp.message(Command("stats"))
async def handle_stats_command(message: types.Message) -> str:
    """
    Обработчик команды /stats
    Показывает баланс пользователя, глобальную статистику и статус модерации в его группах
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

        # Получаем расширенную статистику (включая данные из Logfire)
        admin_stats = await get_admin_stats(user_id)
        global_stats = admin_stats["global"]
        groups = admin_stats["groups"]

        # Формируем сообщение
        # Баланс и расходы
        message_text = (
            f"💰 Баланс: <b>{balance}</b> звезд\n"
            f"📊 Потрачено за последние 7 дней: <b>{spent_week}</b> звезд\n\n"
        )

        # Глобальная статистика за неделю
        message_text += (
            "<b>Статистика за 7 дней:</b>\n"
            f"📨 Обработано сообщений: <b>{global_stats['processed']}</b>\n"
            f"🗑 Заблокировано спама: <b>{global_stats['spam']}</b>\n\n"
            "<b>За все время:</b>\n"
            f"👤 Одобрено пользователей: <b>{global_stats['approved']}</b>\n"
            f"📝 Сохраненных примеров спама: <b>{global_stats['spam_examples']}</b>\n\n"
        )

        # Список групп
        if groups:
            message_text += "<b>По группам:</b>\n"
            for group in groups:
                status_emoji = "✅" if group["is_moderation_enabled"] else "❌"
                safe_title = sanitize_html(group["title"])
                g_stats = group["stats"]

                # Формируем строку статистики группы
                stats_line = (
                    f"   └ 📨 {g_stats['processed']} | "
                    f"🗑 {g_stats['spam']} | "
                    f"👤 {group['approved_users_count']}"
                )

                message_text += f"{status_emoji} <b>{safe_title}</b>\n{stats_line}\n"
        else:
            message_text += "У вас нет групп, где вы администратор."

        # Добавляем информацию о режиме работы
        delete_spam = await get_spam_deletion_state(user_id)
        mode = "🗑 Режим удаления" if delete_spam else "🔔 Режим уведомлений"
        message_text += f"\n\nТекущий режим: <b>{mode}</b>"

        # Трекинг просмотра статистики
        mp.track(
            user_id,
            "command_stats",
            {
                "user_id": user_id,
                "balance": balance,
                "spent_week": spent_week,
                "groups_count": len(groups),
                "deletion_mode": delete_spam,
                "chat_type": message.chat.type,
                "total_processed": global_stats["processed"],
                "total_spam": global_stats["spam"],
            },
        )

        await message.reply(message_text, parse_mode="HTML")
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
        await message.reply(
            "Произошла ошибка при получении статистики.", parse_mode="HTML"
        )
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
                "🗑 Включен <b>режим удаления</b>\n\n"
                "Теперь я буду автоматически удалять сообщения, "
                "определённые как спам, в ваших группах."
            )
        else:
            message_text = (
                "🔔 Включен <b>режим уведомлений</b>\n\n"
                "Теперь я буду только уведомлять о сообщениях, "
                "определённых как спам, но не буду их удалять."
            )

        await message.reply(message_text, parse_mode="HTML")
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
        await message.reply(
            "Произошла ошибка при изменении режима работы.", parse_mode="HTML"
        )
        return "command_mode_error"


@dp.message(Command("ref"), F.chat.type == "private")
async def cmd_ref(message: types.Message):
    """Объясняет, как получить официальную реферальную ссылку Telegram Partner Program"""
    await message.answer(
        "<b>Как получить свою реферальную ссылку для этого бота:</b>\n\n"
        "1. Откройте профиль этого бота в Telegram.\n"
        "2. Нажмите <b>Партнёрская программа</b>.\n"
        "3. Нажмите <b>Участвовать</b>.\n"
        "4. После этого появится ваша персональная реферальная ссылка — её можно скопировать и отправить друзьям.\n\n"
        f"<i>Подробнее: {get_affiliate_url()}</i>",
        parse_mode="HTML",
    )
