"""
Message processing pipeline.

This module contains the core message moderation pipeline that orchestrates
the entire message processing flow from validation to spam analysis to result processing.
"""

import logging

from aiogram import types
from opentelemetry.trace import get_current_span

from ...database import APPROVE_PRICE, DELETE_PRICE, add_member
from ..handle_spam import handle_spam
from ..try_deduct_credits import try_deduct_credits
from .validation import (
    check_skip_channel_bot_message,
    determine_effective_user_id,
    validate_group_and_check_early_exits,
)
from ...spam.message_context import collect_message_context
from ...spam.spam_classifier import is_spam

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

        # Validate group and check for early exits
        group, exit_reason = await validate_group_and_check_early_exits(
            chat_id, user_id
        )
        if exit_reason or group is None:
            return exit_reason

        # At this point group is guaranteed to be not None

        # Check if message should be skipped
        logger.debug(
            f"sender_chat={getattr(message, 'sender_chat', None)}, "
            f"chat.linked_chat_id={getattr(message.chat, 'linked_chat_id', None)}"
        )
        skip, reason = await check_skip_channel_bot_message(message)
        if skip:
            return reason

        # Collect message data for spam analysis
        analysis_result = await collect_message_context(message)

        # Perform spam classification
        try:
            if analysis_result.is_story:
                # Stories are always considered spam
                spam_score, confidence, reason = 100, 100, "Story forward"
            else:
                # Perform LLM-based spam classification
                spam_score, confidence, reason = await is_spam(
                    comment=analysis_result.message_text,
                    admin_ids=group.admin_ids,
                    context=analysis_result.context,
                )
        except Exception as e:
            logger.warning(f"Failed to get spam score: {e}")
            return "message_spam_check_failed"

        if spam_score is None:
            logger.warning("Failed to get spam score")
            return "message_spam_check_failed"

        # Set LLM response and context attributes on the root span
        current_span = get_current_span()
        if current_span:
            current_span.set_attribute("llm_score", spam_score)
            current_span.set_attribute("llm_confidence", confidence)
            current_span.set_attribute("llm_reason", reason)

            # Set user context attributes
            if analysis_result.bio:
                current_span.set_attribute("user_bio", analysis_result.bio)

            if analysis_result.context.name:
                current_span.set_attribute("user_name", analysis_result.context.name)

            # Set linked channel info if available
            if analysis_result.context.linked_channel:
                if (
                    analysis_result.context.linked_channel.status == "found"
                    and analysis_result.context.linked_channel.content
                ):
                    channel_info = analysis_result.context.linked_channel.content.to_prompt_fragment()
                    current_span.set_attribute("linked_channel_info", channel_info)

            # Set stories info if available
            if analysis_result.context.stories:
                if analysis_result.context.stories.status == "found":
                    current_span.set_attribute(
                        "user_stories", analysis_result.context.stories.content or ""
                    )

            # Set account age info if available
            if analysis_result.context.account_age:
                if (
                    analysis_result.context.account_age.status == "found"
                    and analysis_result.context.account_age.content
                ):
                    age_info = (
                        analysis_result.context.account_age.content.to_prompt_fragment()
                    )
                    current_span.set_attribute("account_age_info", age_info)

            # Set reply context if available
            if analysis_result.context.reply:
                current_span.set_attribute(
                    "reply_context", analysis_result.context.reply
                )

        # Process spam or approve user
        return await process_spam_or_approve(
            chat_id, user_id, spam_score, message, group.admin_ids, reason
        )

    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        raise


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
        spam_score: The spam score from classification
        message: The original message
        admin_ids: List of admin IDs for the group

    Returns:
        Result identifier string
    """
    if spam_score > 50:
        if await try_deduct_credits(chat_id, DELETE_PRICE, "delete spam"):
            return await handle_spam(message, admin_ids, reason)

    elif await try_deduct_credits(chat_id, APPROVE_PRICE, "approve user"):
        await add_member(chat_id, user_id)
        return "message_user_approved"
    return "message_insufficient_credits"
