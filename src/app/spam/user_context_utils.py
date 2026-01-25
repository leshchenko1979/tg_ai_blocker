"""
Utilities for user context collection that can be imported without circular dependencies.
"""

import logging
from typing import Optional

import logfire

from ..common.mtproto_client import MtprotoHttpError, get_mtproto_client

logger = logging.getLogger(__name__)


@logfire.instrument(extract_args=True)
async def subscribe_user_bot_to_chat(chat_id: int, chat_username: Optional[str] = None) -> bool:
    """
    Attempts to subscribe the user bot to a chat using MTProto channels.joinChannel.

    Args:
        chat_id: Bot API chat ID (can be negative for channels/supergroups)
        chat_username: Optional username of the chat

    Returns:
        bool: True if subscription succeeds or bot is already subscribed, False otherwise

    Handles:
        - UserAlreadyParticipantError: Already subscribed (treats as success)
        - ChannelPrivateError: Private channel can't be joined
        - Other errors: Logs and returns False

    Note: Cannot subscribe to chats without usernames (private channels).
    """
    client = get_mtproto_client()

    # Cannot subscribe to chats without usernames (private channels)
    if not chat_username:
        logger.debug(
            "Skipping subscription to chat without username (likely private)",
            extra={"chat_id": chat_id, "chat_username": chat_username},
        )
        return False

    # Use username for subscription (only attempt subscription for public channels)
    identifier = chat_username

    with logfire.span("Subscribing user bot to chat", chat_id=chat_id, chat_username=chat_username):
        try:
            logger.debug(f"Attempting to subscribe user bot to chat with identifier: {identifier}")
            await client.call("channels.joinChannel", params={"channel": identifier}, resolve=True)

            logger.info(
                "Successfully subscribed user bot to chat",
                extra={
                    "chat_id": chat_id,
                    "chat_username": chat_username,
                    "identifier_used": identifier,
                },
            )
            return True

        except MtprotoHttpError as e:
            error_msg = str(e).lower()

            # Already subscribed - treat as success
            if "user already participant" in error_msg or "already" in error_msg:
                logger.debug(
                    "User bot already subscribed to chat",
                    extra={"chat_id": chat_id, "chat_username": chat_username},
                )
                return True

            # Private channel - can't join
            if "channel private" in error_msg or "private" in error_msg:
                logger.info(
                    "Cannot subscribe user bot to private chat",
                    extra={
                        "chat_id": chat_id,
                        "chat_username": chat_username,
                        "error": str(e),
                    },
                )
                return False

            # Other errors - log and return False
            logger.warning(
                "Failed to subscribe user bot to chat",
                extra={
                    "chat_id": chat_id,
                    "chat_username": chat_username,
                    "identifier": identifier,
                    "error": str(e),
                },
            )
            return False

        except Exception as e:
            logger.error(
                "Unexpected error subscribing user bot to chat",
                extra={
                    "chat_id": chat_id,
                    "chat_username": chat_username,
                    "identifier": identifier,
                    "error": str(e),
                },
                exc_info=True,
            )
            return False


@logfire.instrument(extract_args=True)
async def ensure_user_context_collectable(
    chat_id: int, user_id: int, message_id: int, chat_username: Optional[str] = None
) -> bool:
    """
    Ensures the user bot is subscribed to the chat and has read the message so that context collection can work for users without usernames.

    This is a DRY helper used by both linked channel and stories collection.

    Args:
        chat_id: Bot API chat ID
        user_id: User ID (for logging)
        message_id: Message ID to read for context
        chat_username: Optional chat username

    Returns:
        bool: True if user bot is subscribed and message is readable, False otherwise
    """
    with logfire.span(
        "Ensuring user bot is subscribed and has read message for context collection",
        chat_id=chat_id,
        user_id=user_id,
        message_id=message_id,
        chat_username=chat_username,
    ):
        # First, try to ensure user bot is subscribed to the chat (only works for public chats)
        subscription_success = await subscribe_user_bot_to_chat(chat_id, chat_username)

        if not subscription_success and chat_username:
            # Subscription failed for a chat that has a username - this is unexpected
            logger.warning(
                "User bot subscription failed for chat with username, skipping context collection",
                extra={
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "message_id": message_id,
                    "chat_username": chat_username,
                },
            )
            return False
        elif not subscription_success and not chat_username:
            # Chat has no username (private) - user bot might still have access if already member
            logger.debug(
                "Chat has no username, proceeding with message reading (user bot may already have access)",
                extra={
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "message_id": message_id,
                    "chat_username": chat_username,
                },
            )

        # Now read the specific message to establish chat context for user resolution
        client = get_mtproto_client()

        # Convert Bot API chat ID to MTProto format
        mtproto_chat_id = chat_id
        if chat_id < 0:
            str_id = str(chat_id)
            if str_id.startswith("-100"):
                mtproto_chat_id = int(str_id[4:])  # Remove -100 prefix
            elif str_id.startswith("-"):
                mtproto_chat_id = int(str_id[1:])  # Remove - prefix

        # Use username if available, otherwise use the MTProto chat ID
        chat_identifier = chat_username if chat_username else mtproto_chat_id

        try:
            logger.debug(
                f"User bot reading message {message_id} in chat for context establishment",
                extra={
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "message_id": message_id,
                    "chat_identifier": chat_identifier,
                },
            )

            # Read the specific message to establish chat context
            message_result = await client.call(
                "messages.getHistory",
                params={
                    "peer": chat_identifier,
                    "offset_id": message_id
                    + 1,  # offset_id is exclusive, so +1 to include our message
                    "offset_date": 0,
                    "add_offset": 0,
                    "limit": 1,  # Just read this one message
                    "max_id": 0,
                    "min_id": 0,
                    "hash": 0,
                },
                resolve=True,
            )

            logger.debug(
                "User bot successfully read message for context establishment",
                extra={
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "message_id": message_id,
                    "messages_found": len(message_result.get("messages", [])),
                },
            )

            return True

        except MtprotoHttpError as e:
            error_msg = str(e).lower()

            # Some errors are acceptable and don't prevent context collection
            if "message not found" in error_msg or "message deleted" in error_msg:
                logger.debug(
                    "Message not found or deleted, but proceeding with context collection",
                    extra={
                        "chat_id": chat_id,
                        "user_id": user_id,
                        "message_id": message_id,
                        "error": str(e),
                    },
                )
                return True  # Message not found is OK, proceed with context collection

            logger.warning(
                "Failed to read message for context establishment",
                extra={
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "message_id": message_id,
                    "chat_identifier": chat_identifier,
                    "error": str(e),
                },
            )
            return False

        except Exception as e:
            logger.error(
                "Unexpected error reading message for context establishment",
                extra={
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "message_id": message_id,
                    "chat_identifier": chat_identifier,
                    "error": str(e),
                },
                exc_info=True,
            )
            return False
