import html
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
)
from ..database import (
    get_admin,
    get_admin_credits,
    get_admin_stats,
    get_spam_deletion_state,
    get_spent_credits_last_week,
    initialize_new_admin,
    toggle_spam_deletion,
    update_admin_username_if_needed,
)
from ..i18n import normalize_lang, resolve_lang, t
from ..spam.user_profile import collect_user_context, collect_channel_summary_by_id
from ..spam.linked_channel_mention import extract_first_channel_mention
from ..types import ContextStatus, ContextResult
from .dp import dp

logger = logging.getLogger(__name__)


@dp.message(F.text.startswith("/"), F.chat.type != "private")
async def delete_and_redirect_to_pm(message: types.Message) -> str:
    """Удаляет команду в группе и отправляет сообщение о переходе в ЛС. Использует answer(), т.к. reply() падает после delete()."""
    try:
        await message.delete()
    except Exception:
        pass
    lang = resolve_lang(message, None)
    group_help_text = t(lang, "group_redirect.title") + t(lang, "group_redirect.body")
    await message.answer(
        group_help_text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    return "command_group_redirect_to_pm"


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

    channel_display = format_chat_or_channel_display(
        chat.title, getattr(chat, "username", None), t("ru", "common.channel")
    )
    user_id = message.from_user.id if message.from_user else 0
    admin = await get_admin(user_id)
    lang = resolve_lang(message, admin)
    offer_text = t(lang, "start.linked_channel_offer", channel_display=channel_display)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "offer.protect_channel"),
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
    admin = await get_admin(user_id)
    lang = resolve_lang(message, admin)

    if command == "/start":
        lang_for_new = normalize_lang(getattr(user, "language_code", None))
        is_new = await initialize_new_admin(user_id, language_code=lang_for_new)
        await update_admin_username_if_needed(user_id, user.username)
        if is_new:
            welcome_text = t(lang, "start.welcome")
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
        existing_user_text = t(lang, "start.existing_user")
        await message.reply(
            existing_user_text,
            parse_mode="HTML",
        )
        return "command_start_existing_user"

    safe_text = t(lang, "help.main")
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "help.buttons.getting_started"),
                    callback_data="help_getting_started",
                ),
                InlineKeyboardButton(
                    text=t(lang, "help.buttons.training"),
                    callback_data="help_training",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "help.buttons.moderation"),
                    callback_data="help_moderation",
                ),
                InlineKeyboardButton(
                    text=t(lang, "help.buttons.commands"),
                    callback_data="help_commands",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "help.buttons.payment"),
                    callback_data="help_payment",
                ),
                InlineKeyboardButton(
                    text=t(lang, "help.buttons.support"),
                    callback_data="help_support",
                ),
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
    admin = await get_admin(user_id)
    lang = resolve_lang(message, admin)

    try:
        balance = await get_admin_credits(user_id)
        spent_week = await get_spent_credits_last_week(user_id)
        admin_stats = await get_admin_stats(user_id)
        global_stats = admin_stats["global"]
        groups = admin_stats["groups"]

        message_text = (
            t(lang, "stats.balance", balance=balance)
            + "\n"
            + t(lang, "stats.spent_week", spent=spent_week)
            + "\n\n"
        )
        message_text += (
            t(lang, "stats.stats_7d")
            + "\n"
            + t(lang, "stats.processed", count=global_stats["processed"])
            + "\n"
            + t(lang, "stats.spam_blocked", count=global_stats["spam"])
            + "\n\n"
            + t(lang, "stats.by_groups")
            + "\n"
            + t(lang, "stats.approved_users", count=global_stats["approved"])
            + "\n"
            + t(lang, "stats.spam_examples", count=global_stats["spam_examples"])
            + "\n\n"
        )

        if groups:
            message_text += t(lang, "stats.by_groups_header") + "\n"
            for group in groups:
                status_emoji = "✅" if group["is_moderation_enabled"] else "❌"
                safe_title = html.escape(group["title"] or "", quote=True)
                g_stats = group["stats"]

                # Формируем строку статистики группы
                stats_line = (
                    f"   └ 📨 {g_stats['processed']} | "
                    f"🗑 {g_stats['spam']} | "
                    f"👤 {group['approved_users_count']}"
                )

                message_text += f"{status_emoji} <b>{safe_title}</b>\n{stats_line}\n"
        else:
            message_text += t(lang, "stats.no_groups")

        delete_spam = await get_spam_deletion_state(user_id)
        mode = (
            t(lang, "stats.mode_delete")
            if delete_spam
            else t(lang, "stats.mode_notify")
        )
        message_text += "\n\n" + t(lang, "stats.current_mode", mode=mode)

        await message.reply(message_text, parse_mode="HTML")
        return "command_stats_sent"

    except Exception as e:
        logger.error(f"Error handling stats command: {e}", exc_info=True)
        await message.reply(t(lang, "stats.error"), parse_mode="HTML")
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
    admin = await get_admin(user_id)
    lang = resolve_lang(message, admin)

    try:
        delete_spam = await toggle_spam_deletion(user_id)

        if delete_spam:
            message_text = t(lang, "mode.delete_enabled")
        else:
            message_text = t(lang, "mode.notify_enabled")

        await message.reply(message_text, parse_mode="HTML")
        return (
            "command_mode_changed_to_deletion"
            if delete_spam
            else "command_mode_changed_to_notification"
        )

    except Exception as e:
        logger.error(f"Error handling mode command: {e}", exc_info=True)
        await message.reply(t(lang, "mode.error"), parse_mode="HTML")
        return "command_mode_error"


@dp.message(Command("ref"), F.chat.type == "private")
async def cmd_ref(message: types.Message) -> str:
    """Объясняет, как получить официальную реферальную ссылку Telegram Partner Program"""
    if not message.from_user:
        return "command_no_user_info"
    admin = await get_admin(message.from_user.id)
    lang = resolve_lang(message, admin)
    text = (
        t(lang, "ref.title")
        + t(lang, "ref.steps")
        + f"<i>Подробнее: {get_affiliate_url()}</i>"
    )
    await message.answer(text, parse_mode="HTML")
    return "command_ref_sent"


@dp.message(Command("lang"), F.chat.type == "private")
async def cmd_lang(message: types.Message) -> str:
    """Change bot language. Private chat only."""
    if not message.from_user:
        return "command_no_user_info"
    admin = await get_admin(message.from_user.id)
    lang = resolve_lang(message, admin)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Русский", callback_data="lang_set:ru"),
                InlineKeyboardButton(text="English", callback_data="lang_set:en"),
            ]
        ]
    )
    await message.answer(
        t(lang, "lang.select"),
        reply_markup=keyboard,
    )
    return "command_lang_sent"
