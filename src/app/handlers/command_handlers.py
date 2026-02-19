import logging
from typing import cast

from aiogram import F, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import Chat, InlineKeyboardButton, InlineKeyboardMarkup

from ..common.bot import bot
from ..common.utils import (
    format_chat_or_channel_display,
    get_affiliate_url,
    get_setup_guide_url,
    load_config,
    sanitize_html,
)
from ..database import (
    get_admin_credits,
    get_admin_stats,
    get_spam_deletion_state,
    get_spent_credits_last_week,
    initialize_new_admin,
    toggle_spam_deletion,
    update_admin_username_if_needed,
)
from ..spam.user_profile import collect_user_context, collect_channel_summary_by_id
from ..spam.linked_channel_mention import extract_first_channel_mention
from ..types import ContextStatus, ContextResult
from .dp import dp

logger = logging.getLogger(__name__)


async def _try_send_linked_channel_offer(
    message: types.Message, user_id: int, username: str | None
) -> bool:
    """
    Collect linked channel (Bot API first, MTProto fallback) and send protect offer.
    Returns True if offer was sent, False otherwise.
    Never queries MTProto by ID—always uses username when available.
    """
    linked = ContextResult(status=ContextStatus.EMPTY)
    display_chat: Chat | None = None  # Cached when from Bot API (personal_chat/bio)
    try:
        chat_full = await bot.get_chat(user_id)
        if chat_full.personal_chat and chat_full.personal_chat.type == "channel":
            personal_chat = chat_full.personal_chat
            channel_id = personal_chat.id
            personal_username = getattr(personal_chat, "username", None)
            linked = await collect_channel_summary_by_id(
                channel_id,
                user_id,
                username=personal_username,
                channel_source="linked",
            )
            if linked.status == ContextStatus.FOUND:
                display_chat = personal_chat
        if linked.status != ContextStatus.FOUND and chat_full.bio:
            candidate_username = extract_first_channel_mention(chat_full.bio)
            if candidate_username:
                try:
                    channel_chat = await bot.get_chat(f"@{candidate_username}")
                    if channel_chat.type in ("channel", "supergroup"):
                        linked = await collect_channel_summary_by_id(
                            channel_chat.id,
                            user_id,
                            username=candidate_username,
                            channel_source="bio",
                        )
                        if linked.status == ContextStatus.FOUND:
                            display_chat = channel_chat
                except Exception:
                    pass
        if linked.status != ContextStatus.FOUND and username:
            user_context = await collect_user_context(user_id, username=username)
            linked = user_context.linked_channel or linked
    except Exception as e:
        logger.warning(
            "Failed to collect context via Bot API for /start offer: %s",
            e,
            exc_info=True,
        )
        return False

    if (
        linked is None
        or linked.status != ContextStatus.FOUND
        or linked.content is None
        or linked.content.channel_id is None
    ):
        return False

    if display_chat is not None:
        chat = display_chat
    else:
        # Linked from collect_user_context (MTProto); bot.get_chat by ID may fail
        try:
            chat = await bot.get_chat(linked.content.channel_id)
        except TelegramBadRequest as e:
            logger.warning(
                "Linked channel not accessible for offer display: %s",
                e,
                extra={"user_id": user_id, "channel_id": linked.content.channel_id},
            )
            return False

    config = load_config()
    channel_display = format_chat_or_channel_display(
        chat.title, getattr(chat, "username", None), "Канал"
    )
    offer_template = config.get(
        "start_linked_channel_offer_template",
        "У вас есть канал {channel_display}. Хотите подключить защиту комментариев?",
    )
    offer_text = offer_template.format(channel_display=channel_display)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Защитить канал",
                    url=get_setup_guide_url(),
                )
            ]
        ]
    )
    await message.answer(
        offer_text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=keyboard,
    )
    logger.info(
        "Sent second /start message with linked channel offer",
        extra={"user_id": user_id, "offer_message": offer_text},
    )
    return True


@dp.message(Command("start", "help"))
async def handle_help_command(message: types.Message) -> str:
    """
    Обработчик команд /start и /help
    Отправляет пользователю справочную информацию и начисляет начальные звезды новым пользователям
    """
    if not message.from_user:
        return "command_no_user_info"

    if not message.text:
        return "command_no_text"

    user = cast("types.User", message.from_user)  # Cast to ensure proper type hints
    user_id = user.id

    command = message.text.split()[0]
    config = load_config()

    if command == "/start":
        is_new = await initialize_new_admin(user_id)
        await update_admin_username_if_needed(user_id, user.username)
        if is_new:
            welcome_text = config.get("start_welcome_text", "Добро пожаловать!")
            await message.reply(
                welcome_text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            logger.info(
                "Sent /start welcome to new user",
                extra={"user_id": user_id, "welcome_message": welcome_text},
            )
            await _try_send_linked_channel_offer(message, user_id, user.username)
            return "command_start_new_user_sent"
        # Для существующих пользователей покажем приветствие с быстрым доступом к функциям
        existing_user_text = config.get("start_existing_user_text", "С возвращением!")
        await message.reply(
            existing_user_text,
            parse_mode="HTML",
        )
        return "command_start_existing_user"

    # Логика для /help
    if message.chat.type != "private":
        # В групповых чатах показываем сообщение о необходимости приватного общения
        group_help_text = (
            "🤖 <b>Команды бота работают только в личных сообщениях</b>\n\n"
            "Чтобы настроить бота или получить помощь, "
            "начните личный разговор со мной: @ai_spam_blocker_bot\n"
        )

        # Удаляем команду из группового чата
        try:
            await message.delete()
        except Exception:
            # Игнорируем ошибки удаления (например, если нет прав)
            pass

        await message.reply(
            group_help_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return "command_help_group_redirect"

    # В приватном чате показываем полную справку
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


@dp.message(Command("stats"), F.chat.type == "private")
async def handle_stats_command(message: types.Message) -> str:
    """
    Обработчик команды /stats
    Показывает баланс пользователя, глобальную статистику и статус модерации в его группах
    """
    if not message.from_user:
        return "command_no_user_info"

    user = cast("types.User", message.from_user)  # Cast to ensure proper type hints
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

        await message.reply(message_text, parse_mode="HTML")
        return "command_stats_sent"

    except Exception as e:
        logger.error(f"Error handling stats command: {e}", exc_info=True)
        await message.reply(
            "Произошла ошибка при получении статистики.", parse_mode="HTML"
        )
        return "command_stats_error"


@dp.message(Command("mode"), F.chat.type == "private")
async def handle_mode_command(message: types.Message) -> str:
    """
    Обработчик команды /mode
    Переключает режим между удалением спама и уведомлениями
    """
    if not message.from_user:
        return "command_no_user_info"

    user = cast("types.User", message.from_user)  # Cast to ensure proper type hints
    user_id = user.id

    try:
        # Переключаем режим
        delete_spam = await toggle_spam_deletion(user_id)

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
        logger.error(f"Error handling mode command: {e}", exc_info=True)
        await message.reply(
            "Произошла ошибка при изменении режима работы.", parse_mode="HTML"
        )
        return "command_mode_error"


@dp.message(Command("ref"), F.chat.type == "private")
async def cmd_ref(message: types.Message) -> str:
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
    return "command_ref_sent"


@dp.message(F.text.startswith("/"), F.chat.type != "private")
async def handle_group_commands(message: types.Message) -> str:
    """
    Handler for any commands sent in group chats (except /help and /start).
    Deletes the command message to prevent other users from accidentally triggering it.
    """
    # Skip /help and /start commands as they are handled separately
    if message.text:
        command = message.text.split()[0].split("@")[0]  # Remove bot mention if present
        if command in ["/help", "/start"]:
            return "command_help_start_allowed"

    try:
        await message.delete()
    except Exception:
        # Ignore deletion errors (e.g., insufficient permissions)
        pass

    return "command_group_deleted"
