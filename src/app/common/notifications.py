import logging

import logfire
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup

from ..database.group_operations import cleanup_group_data
from .bot import bot
from .utils import retry_on_network_error

logger = logging.getLogger(__name__)


@logfire.instrument(extract_args=True, record_return=True)
async def perform_complete_group_cleanup(group_id: int) -> bool:
    """Perform complete group cleanup: leave chat and clean database. Returns success status."""
    try:
        # Leave the group first (bot operation)
        await bot.leave_chat(group_id)

        # Clean up database records (database operation)
        await cleanup_group_data(group_id)

        return True

    except Exception as cleanup_e:
        logger.error(
            f"Failed to perform complete cleanup for group {group_id}: {cleanup_e}",
            exc_info=True,
        )
        return False


@logfire.instrument(extract_args=True, record_return=True)
async def notify_admins_with_fallback_and_cleanup(
    bot,
    admin_ids: list[int],
    group_id: int,
    private_message: str,
    group_message_template: str = "{mention}, я не могу отправить ни одному администратору личное сообщение. Пожалуйста, напишите мне в личку, чтобы получать важные уведомления о группе!",
    cleanup_if_group_fails: bool = True,
    parse_mode: str = "HTML",
    reply_markup: InlineKeyboardMarkup | None = None,
    assume_human_admins: bool = False,
) -> dict:
    """
    Notifies all admins in private, falls back to group if none are reachable.
    Uses the last accessible admin for the group mention.
    Cleans up group if group message fails.
    Returns a dict with results.
    """
    notified_private = []
    unreachable = []
    bots_skipped = []
    last_admin_info = None

    for admin_id in admin_ids:
        try:
            # Fast path: if admins are pre-filtered, skip expensive bot detection
            if assume_human_admins:
                # Skip bot detection entirely - trust the caller
                admin_chat = None
            else:
                # Get admin chat info with retry (expensive API call)
                @retry_on_network_error
                async def get_chat_info():
                    return await bot.get_chat(admin_id)

                admin_chat = await get_chat_info()

                # Check if this is a bot account
                is_bot = False
                if getattr(admin_chat, "type", None) == "private":
                    # Primary check: API-reported bot status
                    is_bot = getattr(admin_chat, "is_bot", False)

                    # Additional check: negative IDs indicate channels/bots
                    if not is_bot and admin_id < 0:
                        is_bot = True
                        logfire.warning(f"Detected channel/bot account {admin_id} with negative ID")

                if is_bot:
                    logfire.info(
                        f"Skipping bot admin {admin_id} ({getattr(admin_chat, 'first_name', 'Unknown')}) - cannot send messages to bots"
                    )
                    bots_skipped.append(admin_id)
                    continue

            # Send message with retry
            @retry_on_network_error
            async def send_private_message():
                return await bot.send_message(
                    admin_id,
                    private_message,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                    disable_web_page_preview=True,
                )

            await send_private_message()

            notified_private.append(admin_id)
            # Use admin_chat if available, otherwise we'll handle fallback without it
            if admin_chat:
                last_admin_info = admin_chat
            logger.debug(f"Successfully notified admin {admin_id} in private")
        except Exception as e:
            # Check if this is a content parsing error vs access/permission error
            if isinstance(e, TelegramBadRequest):
                # Check for specific parsing errors in the message
                error_msg = str(e)
                if "can't parse entities" in error_msg or "Unsupported start tag" in error_msg:
                    logger.error(
                        f"Content parsing error when notifying admin {admin_id}: {e}. "
                        "This indicates malformed HTML in the notification message content.",
                        exc_info=True,
                        extra={
                            "error_message": error_msg,
                            "private_message": private_message,
                        },
                    )
                    # Don't treat content parsing errors as "unreachable admin"
                    # These should be fixed in the message formatting, not trigger fallback
                    continue
                else:
                    # Other TelegramBadRequest errors (like invalid chat_id) should be treated as unreachable
                    logger.warning(
                        f"Telegram API error when notifying admin {admin_id}: {e}",
                        exc_info=True,
                    )
                    unreachable.append(admin_id)
            else:
                logger.info(f"Failed to notify admin {admin_id} in private: {e}", exc_info=True)
                unreachable.append(admin_id)
            try:

                @retry_on_network_error
                async def get_chat_info_fallback():
                    return await bot.get_chat(admin_id)

                admin_chat = await get_chat_info_fallback()
                last_admin_info = admin_chat
            except Exception:
                pass

    result = {
        "notified_private": notified_private,
        "unreachable": unreachable,
        "bots_skipped": bots_skipped,
        "group_notified": False,
        "group_cleaned_up": False,
    }

    if notified_private:
        return result

    # No admins reachable in private, send group message
    with logfire.span("group_fallback_attempt", group_id=group_id):
        mention = None
        if last_admin_info:
            if getattr(last_admin_info, "username", None):
                # Usernames should not be escaped - they are literal text
                mention = f"@{last_admin_info.username}"
            else:
                mention = (
                    f'<a href="tg://user?id={last_admin_info.id}">админ</a>'
                    if parse_mode == "HTML"
                    else f"[админ](tg://user?id={last_admin_info.id})"
                )
            logger.info(f"Using mention '{mention}' for group fallback in chat {group_id}")
        else:
            mention = "админ"
            logger.warning(
                f"No admin info available for group fallback in chat {group_id}, using generic mention"
            )

        group_message = group_message_template.format(mention=mention)
        logger.info(f"Sending group fallback message to chat {group_id}: {group_message[:100]}...")

        try:

            @retry_on_network_error
            async def send_group_message():
                return await bot.send_message(
                    group_id,
                    group_message,
                    parse_mode=parse_mode,
                    disable_web_page_preview=True,
                )

            await send_group_message()
            result["group_notified"] = True
            return result
        except Exception as group_e:
            logger.warning(
                f"Failed to send group fallback notification to chat {group_id}: {group_e}",
                exc_info=True,
            )
            if cleanup_if_group_fails:
                cleanup_success = await perform_complete_group_cleanup(group_id)
                result["group_cleaned_up"] = cleanup_success
                if cleanup_success:
                    logger.info(
                        f"Group {group_id} cleaned up due to inability to notify admins - all notification methods failed"
                    )
            else:
                logger.info(
                    f"Cleanup disabled for group {group_id}, leaving group accessible despite notification failure"
                )

            # Log specific error if all notifications failed
            if not result["notified_private"] and not result["group_notified"]:
                logger.error(
                    f"Failed to notify admins - all notification methods failed for chat {group_id}"
                    + (", cleanup initiated" if cleanup_if_group_fails else "")
                )

            return result
