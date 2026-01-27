import asyncio
import logging
from typing import Optional, Union

import logfire

from .context_types import (
    ContextResult,
    ContextStatus,
    SpamClassificationContext,
    UserContext,
)
from .stories import collect_user_stories
from .user_profile import collect_user_context, collect_channel_summary_by_id
from .user_context_utils import subscribe_user_bot_to_chat

logger = logging.getLogger(__name__)


@logfire.instrument()
async def collect_complete_user_context(
    message,
    user_id: int,
    username: Optional[str] = None,
) -> UserContext:
    """
    Collects complete user context including stories and profile info in parallel.
    Returns a UserContext with ContextResult objects for each context type.

    Args:
        message: Telegram message object containing chat and thread information
        user_id: User ID for context collection
        username: Optional username for the user
    """
    # Extract information from message object
    chat_id = message.chat.id
    message_id = getattr(message, "message_id", None)
    chat_username = getattr(message.chat, "username", None)
    message_thread_id = getattr(message, "message_thread_id", None)
    is_topic_message = getattr(message, "is_topic_message", False)
    linked_chat_id = getattr(message.chat, "linked_chat_id", None)
    reply_to_message_id = None
    original_channel_post_id = None

    if hasattr(message, "reply_to_message") and message.reply_to_message:
        reply_to_message_id = getattr(message.reply_to_message, "message_id", None)
        # For discussion threads, get the original channel post ID from the forwarded message
        if linked_chat_id and message_thread_id and not is_topic_message:
            original_channel_post_id = getattr(message.reply_to_message, "forward_from_message_id", None)

    with logfire.span(
        "Collecting complete user context",
        user_id=user_id,
        username=username,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
        is_topic_message=is_topic_message,
        thread_type="forum_topic"
        if is_topic_message
        else "discussion_thread"
        if message_thread_id
        else "none",
    ):
        # Check if we need to subscribe user bot for context collection (when username is None)
        if username is None and message_id is not None:
            subscription_success = await subscribe_user_bot_to_chat(
                chat_id,
                user_id,
                message_id,
                chat_username,
                message_thread_id,
                reply_to_message_id,
                is_topic_message,
                linked_chat_id,
                original_channel_post_id,
            )
        else:
            subscription_success = (
                True  # No subscription needed if we have username or missing params
            )

        if not subscription_success:
            # Subscription failed, skip all context collection
            return UserContext(
                stories=ContextResult(
                    status=ContextStatus.SKIPPED, error="User bot subscription failed"
                ),
                linked_channel=ContextResult(
                    status=ContextStatus.SKIPPED, error="User bot subscription failed"
                ),
                account_info=ContextResult(
                    status=ContextStatus.SKIPPED, error="User bot subscription failed"
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


@logfire.instrument()
async def collect_sender_context(
    message,
    chat_id: Optional[int] = None,
) -> Union[UserContext, SpamClassificationContext]:
    """
    Unified context collection for both users and channels.
    Returns appropriate context type based on sender.

    Args:
        message: Telegram message object
        chat_id: Optional chat ID for additional context

    Returns:
        UserContext for user senders, SpamClassificationContext for channel senders
    """
    if message.sender_chat and message.sender_chat.id != message.chat.id:
        # Channel sender - collect channel as linked channel
        channel_id = message.sender_chat.id
        channel_username = getattr(message.sender_chat, "username", None)

        # For private channels without username, skip collection
        if not channel_username:
            logger.debug(
                "Skipping context collection for private channel without username",
                extra={"channel_id": channel_id},
            )
            return SpamClassificationContext(
                name=getattr(message.sender_chat, "title", "Channel"),
                bio=getattr(message.chat, "description", None),
                linked_channel=ContextResult(
                    status=ContextStatus.SKIPPED,
                    error="Private channel without username",
                ),
            )

        # Collect channel context using existing function
        channel_result = await collect_channel_summary_by_id(
            channel_id, user_reference=channel_id, username=channel_username
        )

        # Return minimal context with linked_channel populated
        return SpamClassificationContext(
            name=getattr(message.sender_chat, "title", "Channel"),
            bio=getattr(message.chat, "description", None),
            linked_channel=channel_result,
        )
    else:
        # User sender - use existing complete context collection
        if message.from_user:
            user_id = message.from_user.id
            username = getattr(message.from_user, "username", None)
        else:
            # Fallback - shouldn't happen in practice
            logger.warning("Message has no sender_chat or from_user")
            return SpamClassificationContext()

        # Use existing logic with subscription check
        return await collect_complete_user_context(
            message=message,
            user_id=user_id,
            username=username,
        )
