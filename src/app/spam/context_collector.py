"""
Context collection orchestration and routing.

This module provides the main entry points for collecting spam analysis context
from different types of senders (users vs channels). It orchestrates the collection
process while delegating specific collection tasks to specialized modules.
"""

import asyncio
import logging
from typing import Optional, Union

import logfire

from ..common.bot import bot
from .context_types import (
    ContextResult,
    ContextStatus,
    PeerResolutionContext,
    SpamClassificationContext,
    UserContext,
)
from .stories import collect_user_stories
from .user_profile import collect_user_context, collect_channel_summary_by_id
from .user_context_utils import establish_peer_resolution_context

logger = logging.getLogger(__name__)


def create_peer_resolution_context_from_message(
    message, user_id: int
) -> PeerResolutionContext:
    """Create PeerResolutionContext from a Telegram message object."""
    # Extract basic message metadata
    chat_id = int(message.chat.id)
    message_id = int(
        message.message_id
    )  # Guaranteed to be not None when this function is called
    chat_username = getattr(message.chat, "username", None)
    message_thread_id = getattr(message, "message_thread_id", None)
    is_topic_message = bool(getattr(message, "is_topic_message", False))

    # Initialize main channel info
    main_channel_id = None
    main_channel_username = None

    # For discussion thread messages (replies to channel posts), extract channel info from reply_to_message
    if (
        message_thread_id
        and not is_topic_message
        and hasattr(message, "reply_to_message")
        and message.reply_to_message
    ):
        reply_to = message.reply_to_message
        # Check if reply_to_message has sender_chat (channel post in discussion)
        if hasattr(reply_to, "sender_chat") and reply_to.sender_chat:
            sender_chat = reply_to.sender_chat
            if getattr(sender_chat, "type", None) == "channel":
                main_channel_id = getattr(sender_chat, "id", None)
                main_channel_username = getattr(sender_chat, "username", None)

    # Initialize reply metadata
    reply_to_message_id = None
    original_channel_post_id = None

    # Add reply metadata
    if hasattr(message, "reply_to_message") and message.reply_to_message:
        reply_to_message_id = getattr(message.reply_to_message, "message_id", None)
        # For discussion threads, get the original channel post ID from the forwarded message
        if (
            hasattr(message, "message_thread_id")
            and message.message_thread_id
            and not getattr(message, "is_topic_message", False)
        ):
            original_channel_post_id = getattr(
                message.reply_to_message, "forward_from_message_id", None
            )

    return PeerResolutionContext(
        chat_id=chat_id,
        user_id=user_id,
        message_id=message_id,
        chat_username=chat_username,
        message_thread_id=message_thread_id,
        reply_to_message_id=reply_to_message_id,
        is_topic_message=is_topic_message,
        main_channel_id=main_channel_id,
        main_channel_username=main_channel_username,
        original_channel_post_id=original_channel_post_id,
    )


async def collect_user_context_with_stories(
    message,
    user_id: int,
    username: Optional[str] = None,
) -> UserContext:
    """
    Collect user context (profile and account info) and stories in parallel.

    This function collects user profile information and stories concurrently,
    but does NOT include complete context collection (hence the specific name).
    Stories collection is handled separately from profile collection for efficiency.

    Args:
        message: Telegram message object containing chat and thread information
        user_id: User ID for context collection
        username: Optional username for the user

    Returns:
        UserContext with profile info and stories, but stories marked as collected separately
    """
    # Extract basic message info needed for stories collection
    chat_id = message.chat.id

    with logfire.span(
        "Collecting complete user context",
        user_id=user_id,
        username=username,
        chat_id=chat_id,
        message_thread_id=getattr(message, "message_thread_id", None),
        is_topic_message=getattr(message, "is_topic_message", False),
        thread_type="forum_topic"
        if getattr(message, "is_topic_message", False)
        else "discussion_thread"
        if getattr(message, "message_thread_id", None)
        else "none",
    ):
        # Establish peer resolution context when username is None
        if username is None and getattr(message, "message_id", None) is not None:
            peer_context = create_peer_resolution_context_from_message(message, user_id)
            context_established = await establish_peer_resolution_context(peer_context)
        else:
            context_established = True  # No context establishment needed if we have username or missing params

        if not context_established:
            # Peer resolution context establishment failed, skip all context collection
            return UserContext(
                stories=ContextResult(
                    status=ContextStatus.SKIPPED,
                    error="Peer resolution context establishment failed",
                ),
                linked_channel=ContextResult(
                    status=ContextStatus.SKIPPED,
                    error="Peer resolution context establishment failed",
                ),
                account_info=ContextResult(
                    status=ContextStatus.SKIPPED,
                    error="Peer resolution context establishment failed",
                ),
            )

        # Run stories and profile collection in parallel
        stories_task = collect_user_stories(user_id, username, chat_id)
        profile_task = collect_user_context(message, username=username)

        try:
            results = await asyncio.gather(
                stories_task, profile_task, return_exceptions=True
            )
            stories_result = results[0]
            profile_result = results[1]

            # Handle stories result
            if isinstance(stories_result, Exception):
                logger.info(
                    "Failed to collect user stories",
                    extra={
                        "user_id": user_id,
                        "username": username,
                        "error": str(stories_result),
                    },
                )
                stories_context = ContextResult(
                    status=ContextStatus.FAILED, error=str(stories_result)
                )
            else:
                stories_context = stories_result

            # Handle profile result
            if isinstance(profile_result, Exception):
                logger.info(
                    "Failed to collect user profile context",
                    extra={
                        "user_id": user_id,
                        "username": username,
                        "error": str(profile_result),
                    },
                )
                # Create empty context with failed status
                profile_context = UserContext(
                    stories=ContextResult(
                        status=ContextStatus.FAILED, error=str(profile_result)
                    ),
                    linked_channel=ContextResult(
                        status=ContextStatus.FAILED, error=str(profile_result)
                    ),
                    account_info=ContextResult(
                        status=ContextStatus.FAILED, error=str(profile_result)
                    ),
                )
            else:
                profile_context = profile_result

            # Combine results into complete UserContext
            return UserContext(
                stories=stories_context,
                linked_channel=profile_context.linked_channel,
                account_info=profile_context.account_info,
            )

        except Exception as exc:
            # Fallback in case gather itself fails
            logger.info(
                "Failed to collect stories and profile data in parallel",
                extra={
                    "user_id": user_id,
                    "username": username,
                    "error": str(exc),
                },
            )
            return UserContext(
                stories=ContextResult(status=ContextStatus.FAILED, error=str(exc)),
                linked_channel=ContextResult(
                    status=ContextStatus.FAILED, error=str(exc)
                ),
                account_info=ContextResult(status=ContextStatus.FAILED, error=str(exc)),
            )


def _extract_channel_sender_info(message) -> tuple[str, Optional[str], Optional[str]]:
    """
    Extract basic information from a channel sender message.

    Args:
        message: Telegram message from a channel sender

    Returns:
        Tuple of (name, bio, username) for the channel sender
    """
    sender_chat = message.sender_chat
    name = getattr(sender_chat, "title", "Channel")
    bio = getattr(message.chat, "description", None)
    username = getattr(sender_chat, "username", None)
    return name, bio, username


async def _collect_channel_sender_context(
    message,
) -> tuple[SpamClassificationContext, str, Optional[str]]:
    """
    Collect context for messages sent on behalf of channels.

    Args:
        message: Telegram message from a channel sender

    Returns:
        Tuple of (context, name, bio) for the channel sender
    """
    name, bio, username = _extract_channel_sender_info(message)
    channel_id = message.sender_chat.id

    # For private channels without username, skip collection
    if not username:
        logger.debug(
            "Skipping context collection for private channel without username",
            extra={"channel_id": channel_id},
        )
        context = SpamClassificationContext(
            name=name,
            bio=bio,
            linked_channel=ContextResult(
                status=ContextStatus.SKIPPED,
                error="Private channel without username",
            ),
        )
        return context, name, bio

    # Collect channel context using existing function
    channel_result = await collect_channel_summary_by_id(
        channel_id, user_reference=channel_id, username=username
    )

    # Return minimal context with linked_channel populated
    context = SpamClassificationContext(
        name=name,
        bio=bio,
        linked_channel=channel_result,
    )
    return context, name, bio


def _extract_user_sender_info(message) -> tuple[int, Optional[str], str]:
    """
    Extract basic information from a user sender message.

    Args:
        message: Telegram message from a user sender

    Returns:
        Tuple of (user_id, username, name) for the user sender
    """
    from_user = message.from_user
    user_id = from_user.id
    username = getattr(from_user, "username", None)
    name = from_user.full_name if from_user else "Unknown"
    return user_id, username, name


async def _collect_user_sender_context(
    message,
) -> tuple[UserContext, str, Optional[str]]:
    """
    Collect context for messages sent by users.

    Args:
        message: Telegram message from a user sender

    Returns:
        Tuple of (context, name, bio) for the user sender
    """
    user_id, username, name = _extract_user_sender_info(message)

    # Fetch bio from user profile via Bot API
    bio = None
    try:
        user_with_bio = await bot.get_chat(user_id)
        bio = user_with_bio.bio if user_with_bio else None
    except Exception:
        bio = None

    # Collect user context with stories
    context = await collect_user_context_with_stories(
        message=message,
        user_id=user_id,
        username=username,
    )
    return context, name, bio


async def collect_sender_context(
    message,
    chat_id: Optional[int] = None,
) -> tuple[Union[UserContext, SpamClassificationContext], str, Optional[str]]:
    """
    Collect context information based on message sender type.

    Routes to appropriate collection strategy:
    - UserContext for user senders (with bio fetched via Bot API)
    - SpamClassificationContext for channel senders (with bio from chat description)

    Args:
        message: Telegram message object
        chat_id: Optional chat ID for additional context (currently unused)

    Returns:
        Tuple of (context, name, bio) where:
        - context: UserContext for user senders, SpamClassificationContext for channel senders
        - name: Sender display name
        - bio: Sender bio/description (may be None)
    """
    # Check if this is a channel sender (message sent on behalf of channel)
    if message.sender_chat and message.sender_chat.id != message.chat.id:
        return await _collect_channel_sender_context(message)
    elif message.from_user:
        return await _collect_user_sender_context(message)
    else:
        # Fallback - shouldn't happen in practice
        logger.warning("Message has no sender_chat or from_user")
        context = SpamClassificationContext()
        return context, "Unknown", None


# Backward compatibility alias
route_sender_context_collection = collect_sender_context
