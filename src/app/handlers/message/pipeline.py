"""
Message processing pipeline.

This module contains the core message moderation pipeline that orchestrates
the entire message processing flow from validation to spam analysis to result processing.
"""

import logging
from typing import Optional

from aiogram import types

from ...common.tracking import track_group_event
from ...database import APPROVE_PRICE, DELETE_PRICE, add_member
from ..handle_spam import handle_spam
from ..try_deduct_credits import try_deduct_credits
from .validation import (
    check_skip_channel_bot_message,
    determine_effective_user_id,
    validate_group_and_permissions,
)
from ...spam.message_context import analyze_message_content, track_spam_check_result

logger = logging.getLogger(__name__)


async def handle_moderated_message(message: types.Message) -> str:
    """
    Handle all messages in moderated groups.

    Processes incoming messages through spam detection pipeline:
    1. Determine effective user ID (handles channel messages)
    2. Validate group exists and moderation is enabled
    3. Check if message should be skipped (admins, service messages, etc.)
    4. Analyze message content for spam using LLM
    5. Process moderation result (delete spam or approve user)

    Args:
        message: The incoming Telegram message to moderate

    Returns:
        Result identifier string for logging/tracking
    """
    try:
        # Determine effective user ID for moderation
        user_id = determine_effective_user_id(message)
        if user_id is None:
            return "message_no_user_info"

        chat_id = message.chat.id

        # Validate group and check permissions (early exits)
        group, permission_error = await validate_group_and_permissions(chat_id, user_id)
        if permission_error or group is None:
            return permission_error

        # At this point group is guaranteed to be not None

        # Check if message should be skipped
        logger.debug(
            f"sender_chat={getattr(message, 'sender_chat', None)}, "
            f"chat.linked_chat_id={getattr(message.chat, 'linked_chat_id', None)}"
        )
        skip, reason = await check_skip_channel_bot_message(message)
        if skip:
            return reason

        # Analyze message content for spam
        spam_score, bio, reason, is_story, message_text = await analyze_message_content(
            message, group
        )

        if spam_score is None:
            logger.warning("Failed to get spam score")
            return "message_spam_check_failed"

        # Process and track the moderation result
        return await process_moderation_result(
            chat_id,
            user_id,
            spam_score,
            message,
            group.admin_ids,
            reason,
            bio,
            message_text,
        )

    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        await track_group_event(
            chat_id,
            "error_message_processing",
            {
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        raise


async def process_moderation_result(
    chat_id: int,
    user_id: int,
    spam_score: float,
    message: types.Message,
    admin_ids: list[int],
    reason: str,
    bio: Optional[str],
    message_text: str,
) -> str:
    """
    Process the spam analysis result and track it.

    Args:
        chat_id: The chat ID where the message was sent
        user_id: The user ID who sent the message
        spam_score: The calculated spam score (0-100)
        message: The original Telegram message
        admin_ids: List of admin IDs for the group
        reason: The reason for the spam classification
        bio: User bio information
        message_text: The processed message content

    Returns:
        Processing result identifier string
    """
    await track_spam_check_result(
        chat_id, user_id, spam_score, message_text, bio, reason
    )
    return await process_spam_or_approve(
        chat_id, user_id, spam_score, message, admin_ids, reason
    )


async def process_spam_or_approve(
    chat_id: int,
    user_id: int,
    spam_score: float,
    message: types.Message,
    admin_ids: list[int],
    reason: str,
) -> str:
    """
    Process spam analysis result - delete spam or approve user.

    Args:
        chat_id: The chat ID
        user_id: The user ID
        spam_score: The spam score (0-100)
        message: The original message
        admin_ids: List of admin IDs for notifications
        reason: The classification reason

    Returns:
        Result identifier string
    """
    if spam_score > 50:
        if await try_deduct_credits(chat_id, DELETE_PRICE, "delete spam"):
            await handle_spam(message, admin_ids, reason)
            return "message_spam_deleted"

    elif await try_deduct_credits(chat_id, APPROVE_PRICE, "approve user"):
        await add_member(chat_id, user_id)
        await track_group_event(
            chat_id,
            "user_approved",
            {
                "chat_id": chat_id,
                "user_id": user_id,
                "spam_score": spam_score,
            },
        )
        return "message_user_approved"
    return "message_insufficient_credits"
