"""Handlers for bot status updates in chats."""

import logging
from datetime import datetime, timezone
from typing import List

from aiogram import F, types
from aiogram.filters import or_f
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..common.bot import bot
from ..common.mp import mp
from ..database import get_group, remove_admin, update_group_admins
from .dp import dp

logger = logging.getLogger(__name__)


@dp.my_chat_member()
async def handle_bot_status_update(event: types.ChatMemberUpdated) -> None:
    """
    Handle updates to bot's status in chats.
    Called when bot is added to or removed from a chat.
    """
    chat_id = event.chat.id
    admin_id = event.from_user.id
    new_status = event.new_chat_member.status
    old_status = event.old_chat_member.status
    chat_title = event.chat.title or "Unnamed Group"

    try:
        if new_status == old_status:
            await _handle_permission_update(event, chat_id, admin_id, chat_title)
            return

        if new_status in ["administrator", "member", "restricted"]:
            await _handle_bot_added(event, chat_id, admin_id, chat_title, new_status)
        elif new_status in ["left", "kicked"]:
            await _handle_bot_removed(event, chat_id, admin_id, chat_title, new_status)

    except Exception as e:
        logger.error(f"Error handling bot status update: {e}", exc_info=True)
        mp.track(
            admin_id,
            "error_status_update",
            {
                "group_id": chat_id,
                "error_type": type(e).__name__,
                "error_message": str(e),
                "new_status": new_status,
                "timestamp": event.date.isoformat(),
            },
        )
        raise


async def _handle_permission_update(
    event: types.ChatMemberUpdated,
    chat_id: int,
    admin_id: int,
    chat_title: str,
) -> None:
    """Handle updates to bot's permissions."""
    if not (
        isinstance(event.old_chat_member, types.ChatMemberAdministrator)
        and isinstance(event.new_chat_member, types.ChatMemberAdministrator)
    ):
        return

    old_rights = {
        "can_delete_messages": event.old_chat_member.can_delete_messages,
        "can_restrict_members": event.old_chat_member.can_restrict_members,
    }
    new_rights = {
        "can_delete_messages": event.new_chat_member.can_delete_messages,
        "can_restrict_members": event.new_chat_member.can_restrict_members,
    }

    if old_rights != new_rights:
        has_all_rights = all(new_rights.values())

        # Получаем группу для проверки времени добавления
        group = await get_group(chat_id)
        added_at = group.created_at if group else event.date
        time_since_added = (event.date - added_at).total_seconds()

        mp.track(
            admin_id,
            "bot_permissions_updated",
            {
                "group_id": chat_id,
                "chat_title": chat_title,
                "old_rights": old_rights,
                "new_rights": new_rights,
                "has_all_required_rights": has_all_rights,
                "timestamp": event.date.isoformat(),
                "setup_step": "grant_permissions" if has_all_rights else "add_bot",
                "time_since_added": time_since_added,
                "time_since_added_minutes": time_since_added / 60,
                "time_since_added_hours": time_since_added / 3600,
            },
        )

        # Если после обновления прав все еще не хватает необходимых прав
        if not has_all_rights:
            # Получаем список админов группы
            admins = await bot.get_chat_administrators(chat_id)
            admin_ids = [admin.user.id for admin in admins if not admin.user.is_bot]
            await _notify_admins_about_rights(
                chat_id, chat_title, event.chat.username, admin_ids
            )
        else:
            # Send promo message when we get all required rights
            await _send_promo_message(
                chat_id,
                chat_title,
                event.chat.username,
                [admin_id],
                admin_id,
            )
            # NEW: Send confirmation to admin
            try:
                chat_title_escaped = (
                    chat_title.replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace("&", "&amp;")
                )
                await bot.send_message(
                    admin_id,
                    f"✅ Настройка завершена! Я получил все необходимые права и теперь защищаю группу <b>{chat_title_escaped}</b>.\n\nЕсли потребуется помощь — напишите мне в личку или воспользуйтесь командой /help.",
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.warning(
                    f"Failed to send setup confirmation to admin {admin_id}: {e}"
                )


async def _handle_bot_added(
    event: types.ChatMemberUpdated,
    chat_id: int,
    admin_id: int,
    chat_title: str,
    new_status: str,
) -> None:
    """Handle bot being added to a group."""
    logger.info(f"Bot added to group {chat_id} with status {new_status}")

    # Add only the admin who added the bot
    await update_group_admins(chat_id, [admin_id])

    # Track initial interaction
    mp.track(
        admin_id,
        "bot_added_to_group",
        {
            "group_id": chat_id,
            "chat_title": chat_title,
            "status": new_status,
            "has_admin_rights": new_status == "administrator",
            "is_group_creator": True,  # Since this admin added the bot
            "timestamp": event.date.isoformat(),
            "setup_step": "add_bot",
            "time_since_added": 0,
            "time_since_added_minutes": 0,
            "time_since_added_hours": 0,
        },
    )

    has_admin_rights = (
        new_status == "administrator"
        and isinstance(event.new_chat_member, types.ChatMemberAdministrator)
        and event.new_chat_member.can_delete_messages
        and event.new_chat_member.can_restrict_members
    )

    if not has_admin_rights:
        await _notify_admins_about_rights(
            chat_id, chat_title, event.chat.username, [admin_id]
        )
    else:
        # Only send promo message if we have admin rights
        await _send_promo_message(
            chat_id,
            chat_title,
            event.chat.username,
            [admin_id],
            admin_id,
        )
        # NEW: Send confirmation to admin
        try:
            chat_title_escaped = (
                chat_title.replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("&", "&amp;")
            )
            await bot.send_message(
                admin_id,
                f"✅ Настройка завершена! Я получил все необходимые права и теперь защищаю группу <b>{chat_title_escaped}</b>.\n\nЕсли потребуется помощь — напишите мне в личку или воспользуйтесь командой /help.",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(
                f"Failed to send setup confirmation to admin {admin_id}: {e}"
            )


async def _handle_bot_removed(
    event: types.ChatMemberUpdated,
    chat_id: int,
    admin_id: int,
    chat_title: str,
    new_status: str,
) -> None:
    """Handle bot being removed from a group."""
    # Skip notifications if the chat is a channel
    if getattr(event.chat, "type", None) == "channel":
        logger.info(f"Bot removed from channel {chat_id}, skipping notifications.")
        return
    logger.info(f"Bot removed from chat `{chat_title}`")

    group = await get_group(chat_id)
    if group and group.admin_ids:
        for current_admin_id in group.admin_ids:
            mp.track(
                current_admin_id,
                "bot_removed_from_group",
                {
                    "group_id": chat_id,
                    "chat_title": chat_title,
                    "removed_by": admin_id,
                    "status": new_status,
                    "timestamp": event.date.isoformat(),
                    "setup_step": "removed",
                },
            )

        await _notify_admins_about_removal(
            chat_id, chat_title, event.chat.username, group.admin_ids
        )


async def _notify_admins_about_rights(
    chat_id: int, chat_title: str, username: str | None, admin_ids: List[int]
) -> None:
    """Notify admins about required bot permissions."""
    for admin_id in admin_ids:
        try:
            chat_title_escaped = (
                chat_title.replace("*", "\\*").replace("_", "\\_").replace("`", "\\`")
            )
            await bot.send_message(
                admin_id,
                "🤖 Приветствую! Для защиты группы мне нужны права администратора\\.\n\n"
                f"Группа: *{chat_title_escaped}*"
                f"{f' \\(@{username}\\)' if username else ''}\n\n"
                "📱 Как настроить права:\n"
                "1\\. Откройте настройки группы \\(три точки ⋮ сверху\\)\n"
                "2\\. Выберите пункт 'Управление группой'\n"
                "3\\. Нажмите 'Администраторы'\n"
                "4\\. Найдите меня в списке администраторов\n"
                "5\\. Включите два права:\n"
                "   • *Удаление сообщений* \\- чтобы удалять спам\n"
                "   • *Блокировка пользователей* \\- чтобы блокировать спамеров\n\n"
                "После настройки прав я смогу защищать группу\\! 🛡",
                parse_mode="MarkdownV2",
            )
        except Exception as e:
            error_msg = str(e).lower()
            if (
                "bot was blocked by the user" in error_msg
                or "bot can't initiate conversation with a user" in error_msg
            ):
                await remove_admin(admin_id)
                logger.info(
                    f"Removed admin {admin_id} from database (bot blocked or no chat started)"
                )
            else:
                logger.warning(f"Failed to notify admin {admin_id}: {e}")

            mp.track(
                admin_id,
                "error_admin_notification",
                {
                    "group_id": chat_id,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "timestamp": datetime.now().isoformat(),
                },
            )


async def _notify_admins_about_removal(
    chat_id: int, chat_title: str, username: str | None, admin_ids: List[int]
) -> None:
    """Notify admins when bot is removed from a group."""
    for admin_id in admin_ids:
        try:
            chat_title_escaped = (
                chat_title.replace("*", "\\*").replace("_", "\\_").replace("`", "\\`")
            )
            await bot.send_message(
                admin_id,
                f"🔔 Я был удален из группы *{chat_title_escaped}*"
                f"{f' \\(@{username}\\)' if username else ''}\n\n"
                "Если это произошло случайно, вы можете добавить меня обратно "
                "и восстановить защиту группы\\.",
                parse_mode="MarkdownV2",
            )
        except Exception as e:
            error_msg = str(e).lower()
            if (
                "bot was blocked by the user" in error_msg
                or "bot can't initiate conversation with a user" in error_msg
            ):
                await remove_admin(admin_id)
                logger.info(
                    f"Removed admin {admin_id} from database (bot blocked or no chat started)"
                )
            else:
                logger.warning(f"Failed to notify admin {admin_id} about removal: {e}")


async def _send_promo_message(
    chat_id: int,
    chat_title: str,
    username: str | None,
    admin_ids: List[int],
    added_by: int,
) -> None:
    """Send promotional message to the group when bot is added."""
    try:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔰 Начать настройку",
                        url=f"https://t.me/{(await bot.get_me()).username}?start=setup_{chat_id}",
                    )
                ]
            ]
        )

        await bot.send_message(
            chat_id,
            "👋 Приветствую всех обитателей этого цифрового пространства!\n\n"
            "Я - искусственный интеллект, созданный для защиты групп от спама "
            "и нежелательного контента.\n\n"
            "🛡 Мои возможности:\n"
            "• Мгновенное определение спамеров\n"
            "• Автоматическое удаление спама\n"
            "• Ведение белого списка участников\n"
            "• Обучение на ваших примерах\n\n"
            "ℹ️ [Узнайте, как работает определение спама](https://t.me/ai_antispam/7)\n"
            "📢 Следите за обновлениями в [канале проекта](https://t.me/ai_antispam)\n\n"
            "Нажмите на кнопку ниже, чтобы начать настройку защиты.",
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.warning(f"Failed to send promo message to group {chat_id}: {e}")
        mp.track(
            added_by,
            "error_promo_message",
            {
                "group_id": chat_id,
                "error_type": type(e).__name__,
                "error_message": str(e),
                "timestamp": datetime.now().isoformat(),
            },
        )


# Фильтр для сервисных сообщений о присоединении/выходе участников
member_service_message_filter = or_f(
    F.new_chat_member.as_("has_new_member"),
    F.new_chat_members.as_("has_new_members"),
    F.left_chat_member.as_("has_left_member"),
)


@dp.message(member_service_message_filter)
async def handle_member_service_message(message: types.Message) -> str:
    """
    Handle service messages about members joining or leaving the chat.
    Deletes these service messages to keep the chat clean.

    Args:
        message: The service message about member changes

    Returns:
        String indicating the result of handling
    """
    try:
        chat_id = message.chat.id
        message_id = message.message_id

        # Log the event
        if getattr(message, "new_chat_member", None) or getattr(
            message, "new_chat_members", None
        ):
            logger.info(
                f"Detected member join message in chat {chat_id}, message_id: {message_id}"
            )
        elif getattr(message, "left_chat_member", None):
            logger.info(
                f"Detected member leave message in chat {chat_id}, message_id: {message_id}"
            )

        # Delete the service message
        try:
            await bot.delete_message(chat_id, message_id)
            logger.info(f"Deleted service message {message_id} in chat {chat_id}")
            return "service_message_deleted"
        except Exception as e:
            logger.warning(
                f"Failed to delete service message {message_id} in chat {chat_id}: {e}",
                exc_info=True,
            )
            return "service_message_delete_failed"

    except Exception as e:
        logger.error(f"Error handling service message: {e}", exc_info=True)
        if message.from_user:
            mp.track(
                message.from_user.id,
                "error_service_message_handling",
                {
                    "group_id": message.chat.id,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
        return "service_message_error"
