"""Message moderation pipeline: validation, spam analysis, result processing."""

import logging

from aiogram import types

from ...common.trace_context import get_root_span

from ...database import (
    APPROVE_PRICE,
    DELETE_PRICE,
    add_member,
    save_message_lookup_entry,
)
from ..handle_spam import handle_spam
from ..try_deduct_credits import try_deduct_credits
from ...common.utils import determine_effective_user_id, load_config
from .validation import (
    check_skip_channel_bot_message,
    validate_group_and_check_early_exits,
)
from ...spam.message_context import collect_message_context
from ...spam.spam_classifier import is_spam as classify_spam
from ...spam.account_signals import build_account_signals_body
from ...types import ContextStatus, MessageContextResult

logger = logging.getLogger(__name__)


def _context_to_lookup_strings(
    message_context_result: "MessageContextResult",
) -> tuple[str | None, str | None]:
    """Extract stories and account_signals body for message_lookup_cache."""
    ctx = message_context_result.context
    stories_context = None
    if ctx.stories:
        if ctx.stories.status == ContextStatus.FOUND and ctx.stories.content:
            stories_context = ctx.stories.content
        elif ctx.stories.status == ContextStatus.EMPTY:
            stories_context = "[EMPTY]"
    account_signals_context = build_account_signals_body(ctx)
    return stories_context, account_signals_context


async def handle_moderated_message(message: types.Message) -> str:
    """
    Process message through spam pipeline: validate, classify, act.

    Returns result identifier for logging (e.g. message_user_approved, spam_auto_deleted).
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
            if exit_reason == "message_known_member_skipped":
                try:
                    msg_text = message.text or message.caption or "[MEDIA_MESSAGE]"
                    reply_text = None
                    if message.reply_to_message:
                        reply_text = (
                            message.reply_to_message.text
                            or message.reply_to_message.caption
                            or "[MEDIA_MESSAGE]"
                        )
                    await save_message_lookup_entry(
                        chat_id=chat_id,
                        message_id=message.message_id,
                        effective_user_id=user_id,
                        message_text=msg_text,
                        reply_to_text=reply_text,
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to save message lookup for approved user: {e}"
                    )
            return exit_reason

        # Check if message should be skipped
        logger.debug(
            f"sender_chat={getattr(message, 'sender_chat', None)}, "
            f"chat.linked_chat_id={getattr(message.chat, 'linked_chat_id', None)}"
        )
        skip, reason = await check_skip_channel_bot_message(message)
        if skip:
            return reason

        # Collect message data for spam analysis
        message_context_result = await collect_message_context(message)

        # Perform spam classification
        try:
            if message_context_result.is_story:
                # Stories are always considered spam
                is_spam, confidence, reason = True, 100, "Story forward"
            else:
                # Perform LLM-based spam classification
                is_spam, confidence, reason = await classify_spam(
                    comment=message_context_result.message_text,
                    admin_ids=group.admin_ids,
                    context=message_context_result.context,
                )
        except Exception as e:
            logger.warning(f"Failed to get spam classification: {e}")
            return "message_spam_check_failed"

        # Set LLM response and context attributes on the root span for trace-level visibility
        target_span = get_root_span()
        target_span.set_attribute("llm_is_spam", is_spam)
        target_span.set_attribute("llm_confidence", confidence)
        target_span.set_attribute("llm_reason", reason)
        target_span.set_attribute("context", str(message_context_result.context))

        # Save full context to lookup cache for forwarded-message recovery
        try:
            stories_ctx, account_ctx = _context_to_lookup_strings(
                message_context_result
            )
            reply_ctx = message_context_result.context.reply
            msg_text = message.text or message.caption or "[MEDIA_MESSAGE]"
            await save_message_lookup_entry(
                chat_id=message.chat.id,
                message_id=message.message_id,
                effective_user_id=user_id,
                message_text=msg_text,
                reply_to_text=reply_ctx,
                stories_context=stories_ctx,
                account_signals_context=account_ctx,
            )
        except Exception as e:
            logger.warning(f"Failed to save message lookup after classification: {e}")

        # Process spam or approve user
        return await process_spam_or_approve(
            message,
            is_spam,
            confidence,
            group.admin_ids,
            reason,
            message_context_result,
        )

    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        raise


async def process_spam_or_approve(
    message: types.Message,
    is_spam: bool,
    confidence: int,
    admin_ids: list[int],
    reason: str,
    message_context_result: "MessageContextResult",
) -> str:
    """Apply spam result: delete/notify or approve user. Returns result identifier."""
    chat_id = message.chat.id
    user_id = determine_effective_user_id(message)
    if user_id is None:
        return "message_no_user_info"

    threshold = load_config().get("spam", {}).get("high_confidence_threshold", 90)

    if is_spam:
        # Spam: high confidence -> auto-delete, low confidence -> notify only
        skip_auto_delete = confidence < threshold
        if await try_deduct_credits(chat_id, DELETE_PRICE, "delete spam"):
            return await handle_spam(
                message,
                admin_ids,
                reason,
                message_context_result,
                skip_auto_delete=skip_auto_delete,
            )

    elif confidence < threshold:
        # Low-confidence not-spam: send for review, optimistic add
        if await try_deduct_credits(chat_id, APPROVE_PRICE, "approve user"):
            await add_member(chat_id, user_id)
            result = await handle_spam(
                message,
                admin_ids,
                reason,
                message_context_result,
                skip_auto_delete=True,
                is_low_confidence_not_spam=True,
                confidence=confidence,
            )
            return "message_low_confidence_review" if result else result

    elif await try_deduct_credits(chat_id, APPROVE_PRICE, "approve user"):
        # High-confidence not-spam: auto-approve
        await add_member(chat_id, user_id)
        return "message_user_approved"

    return "message_insufficient_credits"
