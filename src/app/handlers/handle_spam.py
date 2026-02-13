"""
Модуль для обработки спам-сообщений в группах Telegram.

Содержит функции для:
- Обработки обнаруженных спам-сообщений
- Уведомления администраторов о спаме
- Автоматического удаления спама
- Блокировки спамеров
"""

import logging
from typing import Optional

from aiogram import types
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..common.bot import bot
from ..common.mcp_client import McpHttpError, get_mcp_client
from ..common.notifications import notify_admins_with_fallback_and_cleanup
from ..common.utils import (
    determine_effective_user_id,
    format_chat_or_channel_display,
    get_project_channel_url,
    get_setup_guide_url,
    get_spam_guide_url,
    load_config,
    retry_on_network_error,
    sanitize_html,
)
from ..database import get_admins_map
from ..database.group_operations import remove_member_from_group
from ..database.spam_examples import insert_pending_spam_example
from ..types import ContextStatus, MessageContextResult, MessageNotificationContext

logger = logging.getLogger(__name__)


def _payload_to_row_values(payload: dict) -> dict:
    """Extract spam_examples row kwargs from payload dict."""
    return {
        "text": payload.get("text") or "[MEDIA_MESSAGE]",
        "name": payload.get("name"),
        "bio": payload.get("bio"),
        "linked_channel_fragment": payload.get("linked_channel_fragment"),
        "stories_context": payload.get("stories_context"),
        "reply_context": payload.get("reply_context"),
        "account_age_context": payload.get("account_age_context"),
    }


def build_spam_example_payload(
    message_context_result: Optional["MessageContextResult"],
    effective_user_id: Optional[int],
) -> dict:
    """Build payload dict for insert_pending_spam_example from MessageContextResult."""
    if not message_context_result:
        return {"text": "[MEDIA_MESSAGE]", "effective_user_id": effective_user_id}

    ctx = message_context_result.context
    payload = {
        "text": message_context_result.message_text or "[MEDIA_MESSAGE]",
        "name": ctx.name if ctx else None,
        "bio": ctx.bio,
        "effective_user_id": effective_user_id,
    }

    if ctx:
        if (
            ctx.linked_channel
            and ctx.linked_channel.status == ContextStatus.FOUND
            and ctx.linked_channel.content
        ):
            payload["linked_channel_fragment"] = (
                ctx.linked_channel.content.to_prompt_fragment()
            )
        if ctx.stories:
            payload["stories_context"] = (
                ctx.stories.content
                if ctx.stories.status == ContextStatus.FOUND
                else "[EMPTY]"
            )
        payload["reply_context"] = ctx.reply
        if ctx.account_age:
            payload["account_age_context"] = (
                ctx.account_age.content.to_prompt_fragment()
                if ctx.account_age.status == ContextStatus.FOUND
                and ctx.account_age.content
                else "[EMPTY]"
            )

    return payload


async def handle_spam(
    message: types.Message,
    admin_ids: list[int],
    reason: str | None = None,
    message_context_result: Optional["MessageContextResult"] = None,
) -> str:
    """
    Обработка спам-сообщений
    """
    try:
        if not message.from_user:
            logger.warning("Message without user info, skipping spam handling")
            return "spam_no_user_info"

        # Проверяем настройки автоудаления у админов
        all_admins_delete = await check_admin_delete_preferences(admin_ids)

        # Уведомление администраторов...
        notification_sent = await notify_admins(
            message, all_admins_delete, admin_ids, reason, message_context_result
        )

        # Отправка MCP уведомлений спамеру/админам канала спамера при обнаружении канала
        if message_context_result and message_context_result.linked_channel_found:
            await notify_spam_contacts_via_mcp(message, reason, message_context_result)

        if all_admins_delete:
            effective_user_id = determine_effective_user_id(message)
            if effective_user_id is None:
                logger.warning("Message without effective user info, skipping ban")
                return "spam_no_user_info"
            await handle_spam_message_deletion(message, admin_ids)
            await ban_user_for_spam(
                message.chat.id, effective_user_id, admin_ids, message.chat.title
            )
            return "spam_auto_deleted"

        return (
            "spam_admins_notified" if notification_sent else "spam_notification_failed"
        )

    except Exception as e:
        logger.error(f"Error handling spam: {e}", exc_info=True)
        raise


async def check_admin_delete_preferences(admin_ids: list[int]) -> bool:
    """
    Проверяет настройки автоудаления спама у администраторов.

    Args:
        admin_ids: Список ID администраторов группы

    Returns:
        bool: True если все админы включили автоудаление, False иначе
    """
    if not admin_ids:
        return False

    admins_map = await get_admins_map(admin_ids)
    for admin_id in admin_ids:
        admin_user = admins_map.get(admin_id)
        if not admin_user or not admin_user.delete_spam:
            return False
    return True


def create_admin_notification_keyboard(
    message: types.Message,
    all_admins_delete: bool,
    pending_id: Optional[int] = None,
) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для уведомления администратора.

    Args:
        message: Спам-сообщение
        all_admins_delete: Флаг автоудаления спама
        pending_id: ID pending spam_example row for "Не спам" button (required for callback)

    Returns:
        InlineKeyboardMarkup: Клавиатура с кнопками действий
    """
    effective_user_id = determine_effective_user_id(message)
    if effective_user_id is None or pending_id is None:
        return InlineKeyboardMarkup(inline_keyboard=[[]])

    if not all_admins_delete:
        row = [
            InlineKeyboardButton(
                text="🗑️ Удалить",
                callback_data=f"delete_spam_message:{effective_user_id}:{message.chat.id}:{message.message_id}",
                style="danger",
            ),
            InlineKeyboardButton(
                text="✅ Не спам",
                callback_data=f"mark_as_not_spam:{pending_id}",
                style="success",
            ),
        ]
    else:
        row = [
            InlineKeyboardButton(
                text="✅ Это не спам",
                callback_data=f"mark_as_not_spam:{pending_id}",
                style="success",
            ),
        ]
    return InlineKeyboardMarkup(inline_keyboard=[row])


def format_missing_permission_message(
    chat_title: str,
    permission_name: str,
    chat_username: Optional[str] = None,
) -> str:
    """
    Форматирует сообщение о отсутствии прав доступа.

    Args:
        chat_title: Название группы
        permission_name: Название отсутствующего права
        chat_username: Опциональный username группы (без @)

    Returns:
        str: Отформатированное сообщение для администраторов
    """
    # Map permission names to user-friendly descriptions
    permission_descriptions = {
        "Удаление сообщений": "удалять спам-сообщения",
        "Блокировка пользователей": "блокировать пользователей",
    }

    action_description = permission_descriptions.get(
        permission_name, permission_name.lower()
    )

    group_display = format_chat_or_channel_display(chat_title, chat_username)
    return (
        f"❗️ У меня нет права {action_description}. "
        f"Пожалуйста, дайте мне право '{permission_name}' для полной защиты.\n\n"
        f"Группа: <b>{group_display}</b>\n\n"
        f'<a href="{get_setup_guide_url()}">ℹ️ Как выдать права боту</a>'
    )


async def handle_permission_error(
    error: Exception,
    chat_id: int,
    admin_ids: list[int] | None,
    group_title: str | None,
    permission_name: str,
    action_description: str,
    group_username: Optional[str] = None,
) -> bool:
    """
    Обрабатывает ошибки связанные с отсутствием прав доступа.

    Args:
        error: Исключение, которое произошло
        chat_id: ID чата
        admin_ids: Список ID администраторов для уведомления
        group_title: Название группы
        permission_name: Название отсутствующего права
        action_description: Описание действия, которое пытались выполнить
        group_username: Опциональный username группы (без @)

    Returns:
        bool: True если это была ошибка прав доступа, False иначе
    """
    if not isinstance(error, TelegramBadRequest):
        return False

    error_message = str(error).lower()
    is_permission_error = (
        "not enough rights" in error_message
        or "need administrator rights" in error_message
        or "chat admin required" in error_message
        or "can_delete_messages" in error_message
        or "can_restrict_members" in error_message
        or "message can't be deleted" in error_message
    )

    if is_permission_error:
        logger.warning(
            f"Cannot {action_description} in chat {chat_id}: {error}",
            exc_info=True,
        )
        # Notify admins about missing permission
        if admin_ids:
            try:
                display_title = group_title or str(chat_id)
                await notify_admins_with_fallback_and_cleanup(
                    bot,
                    admin_ids,
                    chat_id,
                    private_message=format_missing_permission_message(
                        display_title, permission_name, group_username
                    ),
                    group_message_template=(
                        f"{{mention}}, у меня нет права {permission_name}. "
                        f"Пожалуйста, дайте мне право '{permission_name}'!\n\n"
                        f'<a href="{get_setup_guide_url()}">ℹ️ Как выдать права боту</a>'
                    ),
                    cleanup_if_group_fails=True,
                    parse_mode="HTML",
                )
            except Exception as notify_exc:
                logger.warning(
                    f"Failed to notify admins about missing rights for {action_description}: {notify_exc}"
                )
        return True

    return False


def format_admin_notification_message(
    context: MessageNotificationContext,
    all_admins_delete: bool,
    reason: str | None = None,
) -> str:
    """
    Форматирует текст уведомления для администратора.

    Args:
        message: Спам-сообщение
        all_admins_delete: Флаг автоудаления спама
        reason: Причина классификации как спам

    Returns:
        str: Отформатированный текст уведомления
    """
    if context.effective_user_id is None:
        return "Ошибка: сообщение без информации о пользователе"

    reason_text = (
        f"<b>Причина:</b><blockquote expandable>{sanitize_html(reason)}</blockquote>\n"
        if reason
        else ""
    )

    admin_msg = (
        "⚠️ <b>ВТОРЖЕНИЕ!</b>\n\n"
        f"<b>Группа:</b> {format_chat_or_channel_display(context.chat_title, context.chat_username)}\n\n"
        f"<b>Нарушитель:</b> {format_chat_or_channel_display(context.violator_name, context.violator_username, 'Пользователь')}\n\n"
        f"<b>Содержание угрозы:</b>\n<blockquote expandable>{context.content_text}</blockquote>\n\n"
        f"{reason_text}{context.forward_source}\n"
    )

    if all_admins_delete:
        admin_msg += (
            "<b>Вредоносное сообщение уничтожено, "
            f"{'канал' if context.is_channel_sender else 'пользователь'} заблокирован.</b>"
        )
    else:
        link = context.message_link or get_project_channel_url()
        admin_msg += (
            f'<a href="{link}">Ссылка на сообщение</a>\n\n'
            "<b>💡 Совет:</b> Используйте команду /mode, "
            "чтобы переключиться в режим автоматического удаления спама."
        )

    admin_msg += (
        "\n\n"
        f'<a href="{get_spam_guide_url()}">'
        "ℹ️ Подробнее о том, как работает определение спама</a>"
    )

    return admin_msg


async def notify_admins(
    message: types.Message,
    all_admins_delete: bool,
    admin_ids: list[int],
    reason: str | None = None,
    message_context_result: Optional["MessageContextResult"] = None,
) -> bool:
    """
    Отправляет уведомления администраторам о спам-сообщении.

    Args:
        message: Спам-сообщение
        all_admins_delete: Флаг автоудаления спама
        admin_ids: IDs of admins to notify
        reason: Причина классификации как спам
        message_context_result: Collected context for payload (used for "Не спам" flow)

    Returns:
        bool: True если хотя бы одно уведомление отправлено успешно
    """
    if not message.from_user:
        return False

    context = MessageNotificationContext.from_message(message)
    private_message = format_admin_notification_message(
        context, all_admins_delete, reason
    )

    pending_id = None
    if context.effective_user_id is not None:
        payload = build_spam_example_payload(
            message_context_result, context.effective_user_id
        )
        row_kwargs = _payload_to_row_values(payload)
        pending_id = await insert_pending_spam_example(
            message.chat.id,
            message.message_id,
            context.effective_user_id,
            **row_kwargs,
        )

    keyboard = create_admin_notification_keyboard(
        message, all_admins_delete, pending_id
    )
    result = await notify_admins_with_fallback_and_cleanup(
        bot,
        admin_ids,
        message.chat.id,
        private_message,
        group_message_template="{mention}, я не могу отправить ни одному администратору личное сообщение. Пожалуйста, напишите мне в личку, чтобы получать важные уведомления о группе!",
        cleanup_if_group_fails=True,
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    return bool(result["notified_private"]) or bool(result["group_notified"])


async def handle_spam_message_deletion(
    message: types.Message, admin_ids: list[int]
) -> None:
    """
    Удаляет спам-сообщение.

    Args:
        message: Сообщение для удаления
    """
    if not message.from_user:
        return

    try:

        @retry_on_network_error
        async def delete_spam_message():
            return await bot.delete_message(message.chat.id, message.message_id)

        await delete_spam_message()
        logger.info(
            f"Deleted spam message {message.message_id} in chat {message.chat.id}"
        )
    except TelegramBadRequest as e:
        # Handle permission errors using unified helper
        if not await handle_permission_error(
            e,
            message.chat.id,
            admin_ids,
            message.chat.title,
            "Удаление сообщений",
            "delete spam message",
            getattr(message.chat, "username", None),
        ):
            # Not a permission error, log as general error
            logger.warning(
                f"Could not delete spam message {message.message_id} in chat {message.chat.id}: {e}",
                exc_info=True,
            )


async def ban_user_for_spam(
    chat_id: int,
    user_id: int,
    admin_ids: list[int] | None = None,
    group_title: str | None = None,
) -> None:
    """
    Банит пользователя в группе и удаляет из approved_members.
    Args:
        chat_id: ID чата
        user_id: ID пользователя
        admin_ids: Список ID администраторов для уведомления об ошибках
        group_title: Название группы (для уведомлений)
    """
    try:

        @retry_on_network_error
        async def ban_spam_user():
            if user_id < 0:
                # It's a channel, use ban_chat_sender_chat
                return await bot.ban_chat_sender_chat(chat_id, sender_chat_id=user_id)
            return await bot.ban_chat_member(chat_id, user_id)

        await ban_spam_user()
        logger.info(f"Banned user {user_id} in chat {chat_id} for spam")
    except TelegramBadRequest as e:
        # Handle permission errors using unified helper
        if not await handle_permission_error(
            e,
            chat_id,
            admin_ids,
            group_title,
            "Блокировка пользователей",
            "ban user",
        ):
            # Not a permission error, log as general error
            logger.warning(
                f"Failed to ban user {user_id} in chat {chat_id}: {e}", exc_info=True
            )
    except Exception as e:
        logger.warning(
            f"Failed to ban user {user_id} in chat {chat_id}: {e}", exc_info=True
        )
    try:
        await remove_member_from_group(user_id, chat_id)
    except Exception as e:
        logger.warning(
            f"Failed to remove user {user_id} from approved_members: {e}", exc_info=True
        )


def build_spam_block_notification_message(
    context: MessageNotificationContext,
    reason: str | None = None,
) -> str:
    """
    Build notification message for spam blocking.

    This message is used for both human spammers and channel admins.

    Args:
        message: The spam message
        reason: Reason for blocking

    Returns:
        Formatted notification message
    """
    # Load config for URLs
    config = load_config()
    project_website = config["system"]["project_website"]
    project_channel = get_project_channel_url()

    # Build message
    notification_msg = (
        f"Ваш комментарий в {context.entity_type} "
        f"<b>{format_chat_or_channel_display(context.entity_name, context.entity_username, 'Канал')}</b> "
        "был заблокирован админом при помощи @ai_antispam_blocker_bot.\n\n"
        f"Ваш комментарий: <blockquote expandable>{context.content_text}</blockquote>\n\n"
    )

    if reason:
        notification_msg += f"Причина блокировки: <blockquote expandable>{sanitize_html(reason)}</blockquote>\n\n"

    notification_msg += f"Сайт бота: {project_website}\nКанал бота: {project_channel}"

    return notification_msg


async def send_mcp_message_to_user(
    *,
    user_id: int,
    username: Optional[str],
    message: str,
    message_type: str,
) -> bool:
    client = get_mcp_client()
    chat_identifier = f"@{username}" if username else str(user_id)
    log_extra = {
        "user_id": user_id,
        "username": username,
        "chat_identifier": chat_identifier,
        "message_type": message_type,
    }
    try:
        await client.call_tool(
            "send_message",
            arguments={
                "chat_id": chat_identifier,
                "message": message,
                "parse_mode": "html",
            },
        )
        logger.info("Sent MCP spam notification", extra=log_extra)
        return True
    except McpHttpError as e:
        logger.warning(
            "Failed to send MCP message",
            extra={**log_extra, "error": str(e)},
            exc_info=True,
        )
        return False
    except Exception as e:
        logger.error(
            "Unexpected error sending MCP message",
            extra={**log_extra, "error": str(e)},
            exc_info=True,
        )
        return False


async def notify_spam_contacts_via_mcp(
    message: types.Message,
    reason: str | None = None,
    message_context_result: Optional["MessageContextResult"] = None,
) -> None:
    """
    Send MCP notifications to spammers and spamming channel admins when spam is blocked.

    Args:
        message: The spam message
        reason: Reason for blocking
        analysis_result: Message analysis result containing channel user information
    """
    channel_users = (
        message_context_result.channel_users if message_context_result else None
    )
    context = MessageNotificationContext.from_message(message)
    notification_msg = build_spam_block_notification_message(context, reason)

    # Check if this is a channel sender
    is_channel_sender = (
        message.sender_chat is not None and message.sender_chat.id != message.chat.id
    )

    if is_channel_sender and channel_users:
        # For channel senders, send to channel admins (filter out bots)
        admin_count = 0
        for user in channel_users:
            if user.get("bot", True):
                continue  # Skip bots

            user_id = user.get("id")
            username = user.get("username")

            if user_id:
                success = await send_mcp_message_to_user(
                    user_id=user_id,
                    username=username,
                    message=notification_msg,
                    message_type="spammer_channel_admin_notification",
                )
                if success:
                    admin_count += 1

        logger.info(
            f"Sent spam notifications to {admin_count} channel admins",
            extra={
                "channel_id": message.sender_chat.id if message.sender_chat else None,
                "total_admins": len(
                    [u for u in channel_users if not u.get("bot", True)]
                ),
                "successful_notifications": admin_count,
            },
        )

    elif not is_channel_sender and message.from_user:
        # For human senders only - never use message.from_user for channel posts
        # (Telegram uses Channel Bot 136817688 as from_user for channel messages)
        user_id = message.from_user.id
        username = getattr(message.from_user, "username", None)
        success = await send_mcp_message_to_user(
            user_id=user_id,
            username=username,
            message=notification_msg,
            message_type="spammer_user_notification",
        )

        if not success:
            return
