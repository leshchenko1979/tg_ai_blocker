"""
Utilities for user context collection and MTProto peer resolution.

This module provides functions for:
- User bot subscription management for public chats
- Establishing peer resolution context through various strategies
- Handling MTProto API interactions for context collection

All functions are designed to be imported without creating circular dependencies.
"""

import logging
from typing import Dict, Optional, Any

import logfire

from ..common.mtproto_client import MtprotoHttpError, get_mtproto_client
from ..common.mtproto_utils import get_mtproto_chat_identifier
from .context_types import PeerResolutionContext

logger = logging.getLogger(__name__)


# Helper functions for error handling and logging
def _is_user_already_participant_error(error_msg: str) -> bool:
    """Check if error indicates user is already a participant."""
    return ERROR_USER_ALREADY_PARTICIPANT in error_msg or ERROR_ALREADY in error_msg


def _is_channel_private_error(error_msg: str) -> bool:
    """Check if error indicates channel is private."""
    return ERROR_CHANNEL_PRIVATE in error_msg or ERROR_PRIVATE in error_msg


def _is_message_not_found_error(error_msg: str) -> bool:
    """Check if error indicates message was not found or deleted."""
    return ERROR_MESSAGE_NOT_FOUND in error_msg or ERROR_MESSAGE_DELETED in error_msg


def _create_chat_context(
    chat_id: int,
    user_id: Optional[int] = None,
    message_id: Optional[int] = None,
    chat_username: Optional[str] = None,
    **extra_fields: Any,
) -> Dict[str, Any]:
    """Create standardized logging context for chat-related operations."""
    context = {"chat_id": chat_id}

    if user_id is not None:
        context["user_id"] = user_id
    if message_id is not None:
        context["message_id"] = message_id
    if chat_username is not None:
        context["chat_username"] = chat_username

    context.update(extra_fields)
    return context


def _log_mtproto_error(
    error: MtprotoHttpError,
    operation: str,
    context: Dict[str, Any],
    log_level: int = logging.WARNING,
) -> None:
    """Standardized logging for MTProto errors."""
    logger.log(
        log_level,
        f"{operation} failed",
        extra={**context, "error": str(error)},
        exc_info=True,
    )


def _log_unexpected_error(
    error: Exception, operation: str, context: Dict[str, Any]
) -> None:
    """Standardized logging for unexpected errors."""
    logger.error(
        f"Unexpected error during {operation}",
        extra={**context, "error": str(error)},
        exc_info=True,
    )


# Constants for MTProto API calls
DEFAULT_MESSAGE_LIMIT = 1
THREAD_MESSAGE_LIMIT = 10
HISTORY_OFFSET_INCREMENT = 1
DEFAULT_OFFSET = 0
DEFAULT_HASH = 0

# Error message patterns for MTProto errors
ERROR_USER_ALREADY_PARTICIPANT = "user already participant"
ERROR_ALREADY = "already"
ERROR_CHANNEL_PRIVATE = "channel private"
ERROR_PRIVATE = "private"
ERROR_MESSAGE_NOT_FOUND = "message not found"
ERROR_MESSAGE_DELETED = "message deleted"

# Context source types
CONTEXT_SOURCE_LINKED_CHANNEL = "linked_channel"
CONTEXT_SOURCE_DISCUSSION_GROUP = "discussion_group"


def determine_thread_type(
    message_thread_id: Optional[int] = None,
    is_topic_message: bool = False,
) -> str:
    """
    Determine the type of thread based on message properties.

    Args:
        message_thread_id: Thread ID if present
        is_topic_message: Whether this is a forum topic message

    Returns:
        Thread type string: "forum_topic", "discussion_thread", or "none"
    """
    if is_topic_message:
        return "forum_topic"
    elif message_thread_id:
        return "discussion_thread"
    else:
        return "none"


def create_peer_resolution_context(
    context: "PeerResolutionContext",
) -> Dict[str, Any]:
    """
    Create a standardized context dictionary for peer resolution operations.

    Args:
        context: PeerResolutionContext object containing all resolution parameters

    Returns:
        Dict containing all context parameters for peer resolution
    """
    return context.to_dict()


@logfire.instrument(extract_args=True)
async def attempt_user_bot_chat_join(
    chat_id: int, chat_username: Optional[str] = None
) -> bool:
    """
    Attempt to join the user bot to a public chat (group/supergroup) using MTProto channels.joinChannel.

    This function tries to join a public group or supergroup using its username.
    It cannot work with private chats that don't have usernames.

    Args:
        chat_id: Bot API chat ID (can be negative for groups/supergroups)
        chat_username: Optional username of the chat for joining

    Returns:
        bool: True if join succeeds or bot is already a member, False otherwise

    Raises:
        No exceptions are raised - all errors are handled internally and logged.

    Note:
        Cannot join chats without usernames (private groups).
        Already being a participant is treated as success.
        Used for establishing peer resolution context in groups where users send messages.
    """
    client = get_mtproto_client()

    # Cannot subscribe to chats without usernames (private channels)
    if not chat_username:
        logger.debug(
            "Skipping subscription to chat without username (likely private)",
            extra=_create_chat_context(chat_id, chat_username=chat_username),
        )
        return False

    context = _create_chat_context(chat_id, chat_username=chat_username)

    with logfire.span(
        "Joining user bot to chat", chat_id=chat_id, chat_username=chat_username
    ):
        try:
            logger.debug(
                f"Attempting to join user bot to chat with identifier: {chat_username}"
            )

            await client.call(
                "channels.joinChannel", params={"channel": chat_username}, resolve=True
            )

            logger.info(
                "Successfully joined user bot to chat",
                extra={**context, "identifier_used": chat_username},
            )
            return True

        except MtprotoHttpError as e:
            error_msg = str(e).lower()

            # Already joined - treat as success
            if _is_user_already_participant_error(error_msg):
                logger.debug("User bot already joined to chat", extra=context)
                return True

            # Private chat - can't join
            if _is_channel_private_error(error_msg):
                logger.info("Cannot join user bot to private chat", extra=context)
                return False

            # Other MTProto errors - log warning and return False
            _log_mtproto_error(e, "user bot chat join", context)
            return False

        except Exception as e:
            _log_unexpected_error(e, "user bot chat join", context)
            return False


@logfire.instrument(extract_args=True)
async def establish_context_via_group_reading(
    chat_id: int, user_id: int, message_id: int, chat_username: Optional[str] = None
) -> bool:
    """
    Establish peer resolution context by reading a specific message from a group chat.

    This function attempts to read a single message from the chat to establish MTProto
    peer resolution context. This is necessary for the user bot to resolve user IDs
    to usernames/peer information when collecting spam context.

    Args:
        chat_id: Bot API chat ID
        user_id: User ID for logging context
        message_id: Specific message ID to read for context establishment
        chat_username: Optional chat username for identifier resolution

    Returns:
        bool: True if context was established successfully, False otherwise

    Note:
        Message not found/deleted errors are treated as acceptable and return True,
        as they don't prevent general context collection for the chat.
    """
    client = get_mtproto_client()
    chat_identifier = get_mtproto_chat_identifier(chat_id, chat_username)
    context = _create_chat_context(
        chat_id, user_id, message_id, chat_username, chat_identifier=chat_identifier
    )

    try:
        logger.debug(
            "Attempting group message reading for context establishment", extra=context
        )

        # Read the specific message to establish chat context
        # offset_id is exclusive, so +1 to include our target message
        message_result = await client.call(
            "messages.getHistory",
            params={
                "peer": chat_identifier,
                "offset_id": message_id + HISTORY_OFFSET_INCREMENT,
                "offset_date": DEFAULT_OFFSET,
                "add_offset": DEFAULT_OFFSET,
                "limit": DEFAULT_MESSAGE_LIMIT,
                "max_id": DEFAULT_OFFSET,
                "min_id": DEFAULT_OFFSET,
                "hash": DEFAULT_HASH,
            },
            resolve=True,
        )

        messages_found = len(message_result.get("messages", []))
        logger.debug(
            "Group message reading succeeded for context establishment",
            extra={**context, "messages_found": messages_found},
        )

        return True

    except MtprotoHttpError as e:
        error_msg = str(e).lower()

        # Message not found/deleted is acceptable for context collection
        if _is_message_not_found_error(error_msg):
            logger.debug(
                "Message not found or deleted during group reading, but proceeding with context collection",
                extra=context,
            )
            return True

        _log_mtproto_error(e, "group message reading", context, log_level=logging.DEBUG)
        return False

    except Exception as e:
        _log_unexpected_error(e, "group message reading", context)
        return False


@logfire.instrument(extract_args=True)
async def establish_context_via_thread_reading(
    chat_id: int,
    user_id: int,
    message_thread_id: int,
    reply_to_message_id: int,
    chat_username: Optional[str] = None,
    linked_chat_id: Optional[int] = None,
    original_channel_post_id: Optional[int] = None,
) -> bool:
    """
    Establish peer resolution context by reading messages from a discussion thread.

    This function is specifically designed for discussion groups linked to channels.
    It reads thread replies from either the linked public channel or the discussion
    group itself to establish MTProto peer context for user resolution.

    For discussion threads, reading from the linked channel (public) is preferred
    over the discussion group (potentially private) to establish peer context.

    Args:
        chat_id: Bot API chat ID of the discussion group
        user_id: User ID for logging context
        message_thread_id: Thread ID for the discussion thread
        reply_to_message_id: ID of the message being replied to
        chat_username: Optional username of the discussion group
        linked_chat_id: Optional ID of the linked channel (preferred for reading)
        original_channel_post_id: Optional ID of the original channel post

    Returns:
        bool: True if context was established successfully, False otherwise
    """
    client = get_mtproto_client()

    # Determine reading strategy based on linked channel availability
    if linked_chat_id:
        # Use the linked channel (public) for reading thread replies
        target_chat_id = linked_chat_id
        target_chat_username = None  # Channel username not needed for ID-based access
        target_message_id = original_channel_post_id or reply_to_message_id
        context_source = CONTEXT_SOURCE_LINKED_CHANNEL
    else:
        # Fallback to discussion group (for backward compatibility)
        target_chat_id = chat_id
        target_chat_username = chat_username
        target_message_id = reply_to_message_id
        context_source = CONTEXT_SOURCE_DISCUSSION_GROUP

    chat_identifier = get_mtproto_chat_identifier(target_chat_id, target_chat_username)
    context = _create_chat_context(
        chat_id,
        user_id,
        reply_to_message_id,
        chat_username,
        message_thread_id=message_thread_id,
        linked_chat_id=linked_chat_id,
        original_channel_post_id=original_channel_post_id,
        target_chat_id=target_chat_id,
        target_message_id=target_message_id,
        context_source=context_source,
        chat_identifier=chat_identifier,
    )

    try:
        logger.debug("Attempting thread-based context establishment", extra=context)

        # Read recent messages in the thread to establish peer context
        # This includes messages from various users, helping with peer resolution
        thread_result = await client.call(
            "messages.getReplies",
            params={
                "peer": chat_identifier,
                "msg_id": target_message_id,  # The message being replied to (channel post)
                "offset_id": DEFAULT_OFFSET,
                "offset_date": DEFAULT_OFFSET,
                "add_offset": DEFAULT_OFFSET,
                "limit": THREAD_MESSAGE_LIMIT,  # Read up to 10 recent messages in the thread
                "max_id": DEFAULT_OFFSET,
                "min_id": DEFAULT_OFFSET,
                "hash": DEFAULT_HASH,
            },
            resolve=True,
        )

        messages_found = len(thread_result.get("messages", []))
        logger.debug(
            "Thread reading succeeded for context establishment",
            extra={**context, "messages_found": messages_found},
        )

        return True

    except MtprotoHttpError as e:
        _log_mtproto_error(
            e, "thread-based context establishment", context, log_level=logging.DEBUG
        )
        return False

    except Exception as e:
        _log_unexpected_error(e, "thread-based context establishment", context)
        return False


@logfire.instrument(extract_args=True)
async def establish_peer_resolution_context(
    context: PeerResolutionContext,
) -> bool:
    """
    Establish MTProto peer resolution context for user context collection.

    This function employs different strategies based on message type to establish peer resolution context,
    which is necessary for the user bot to resolve user IDs when usernames are not available.

    **Discussion Thread Messages** (replies to channel posts in discussion groups):
    - Uses thread-based reading from the linked channel (preferred) or discussion group
    - No subscription attempt needed as we read from public channels

    **Regular Group Messages** (standard group chats or forum topics):
    - Attempts user bot subscription for public chats with usernames
    - Falls back to direct message reading if subscription succeeds or chat is already accessible

    Args:
        context: PeerResolutionContext object containing all resolution parameters

    Returns:
        bool: True if peer resolution context was established successfully, False otherwise

    Note:
        Context establishment is crucial for the user bot to resolve user IDs to peer information
        when collecting spam analysis context. Different chat types require different strategies.
    """
    thread_type = determine_thread_type(
        context.message_thread_id, context.is_topic_message
    )

    context_dict = create_peer_resolution_context(context)
    context_dict["thread_type"] = thread_type
    with logfire.span(
        "Ensuring peer resolution context for user",
        **context_dict,
    ):
        # Choose context establishment strategy based on message type
        if context.message_thread_id and not context.is_topic_message:
            return await _establish_context_for_discussion_thread(context_dict)
        else:
            return await _establish_context_for_group_message(context_dict)


async def _establish_context_for_discussion_thread(context: Dict[str, Any]) -> bool:
    """
    Establish context for discussion thread messages (replies to channel posts).

    Uses thread-based reading strategy without attempting subscription,
    as discussion threads are typically linked to public channels.
    """
    logger.debug(
        "Discussion thread detected (channel reply), using thread-based peer resolution",
        extra=context,
    )

    return await establish_context_via_thread_reading(
        context["chat_id"],
        context["user_id"],
        context["message_thread_id"],
        context["reply_to_message_id"],
        context.get("chat_username"),
        context.get("linked_chat_id"),
        context.get("original_channel_post_id"),
    )


async def _establish_context_for_group_message(context: Dict[str, Any]) -> bool:
    """
    Establish context for regular group messages or forum topic messages.

    Attempts user bot subscription for public chats, then uses direct message reading.
    """
    message_type = "forum_topic" if context.get("is_topic_message") else "regular_group"
    logger.debug(
        f"{message_type} message, using subscription + group reading", extra=context
    )

    # Attempt join for public chats (only works if chat has username)
    join_success = await attempt_user_bot_chat_join(
        context["chat_id"], context.get("chat_username")
    )

    # Handle join results
    if not join_success:
        if context.get("chat_username"):
            # Subscription failed for a chat that has a username - unexpected
            logger.warning(
                "User bot subscription failed for chat with username, skipping context collection",
                extra=context,
            )
            return False
        else:
            # Chat has no username (private) - user bot might still have access if already member
            logger.debug(
                "Chat has no username, proceeding with message reading (user bot may already have access)",
                extra=context,
            )

    # Use group reading for context establishment
    return await establish_context_via_group_reading(
        context["chat_id"],
        context["user_id"],
        context["message_id"],
        context.get("chat_username"),
    )
