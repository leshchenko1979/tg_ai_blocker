"""
Message context collection and spam analysis.

This module handles the extraction of context information from messages
and performs spam analysis using the collected context.
"""

import logging
from typing import Optional, Tuple, Union

from aiogram import types

from ..types import (
    ContextStatus,
    MessageContextResult,
    SpamClassificationContext,
    UserContext,
)
from .context_collector import route_sender_context_collection

logger = logging.getLogger(__name__)


async def collect_message_context(
    message: types.Message,
) -> MessageContextResult:
    """
    Collect all relevant context data for message analysis.

    This function focuses solely on data collection and does not perform
    the actual spam classification.

    Args:
        message: The Telegram message to analyze

    Returns:
        MessageContextResult containing all context data
    """
    message_text, is_story = extract_message_with_forward_context(message)

    reply_context = extract_reply_context(message)
    sender_context, name, bio = await route_sender_context_collection(
        message, message.chat.id
    )

    context = create_classification_context(sender_context, name, bio, reply_context)

    # Extract context flags and users
    linked_channel_found = False
    channel_users = None

    if isinstance(sender_context, UserContext):
        # Channel found if linked_channel was successfully found
        linked_channel_found = (
            sender_context.linked_channel.status == ContextStatus.FOUND
        )
        # For human senders, we don't collect channel users (only send to spammer directly)
    else:
        # For channel senders, channel is always found
        linked_channel_found = True
        # Extract users from the channel context for admin notifications
        if sender_context.linked_channel and sender_context.linked_channel.content:
            channel_users = sender_context.linked_channel.content.users

    return MessageContextResult(
        message_text,
        is_story,
        bio,
        context,
        linked_channel_found,
        channel_users,
    )


def extract_reply_context(message: types.Message) -> Optional[str]:
    """
    Extract context from the message being replied to.

    Args:
        message: The message that might be a reply

    Returns:
        Reply context text if this is a reply, None otherwise
    """
    if not message.reply_to_message:
        return None

    return (
        message.reply_to_message.text
        or message.reply_to_message.caption
        or "[MEDIA_MESSAGE]"
    )


def create_classification_context(
    sender_context: Union[UserContext, SpamClassificationContext],
    name: str,
    bio: Optional[str],
    reply_context: Optional[str],
) -> SpamClassificationContext:
    """
    Create spam classification context from sender context.

    Args:
        sender_context: The raw sender context
        name: Sender name
        bio: Sender bio
        reply_context: Context from replied message

    Returns:
        SpamClassificationContext for classification
    """
    if isinstance(sender_context, UserContext):
        return SpamClassificationContext(
            name=name,
            bio=bio,
            linked_channel=sender_context.linked_channel,
            stories=sender_context.stories,
            reply=reply_context,
            account_age=sender_context.account_info,
        )
    else:
        # Channel sender - context is already SpamClassificationContext, just add reply
        sender_context.reply = reply_context
        return sender_context


def _extract_message_text(message: types.Message) -> str:
    """Extract the text content from a message, handling different message types."""
    return message.text or message.caption or "[MEDIA_MESSAGE]"


def _collect_forward_info(message: types.Message) -> list[str]:
    """Collect information about forwarded content in the message."""
    forward_info = []

    if message.forward_from:
        forward_info.append(f"Forwarded from user: {message.forward_from.full_name}")

    if message.forward_from_chat:
        forward_info.append(f"Forwarded from chat: {message.forward_from_chat.title}")

    return forward_info


def _collect_story_info(message: types.Message) -> tuple[list[str], bool]:
    """Collect information about stories and determine if message is from a story."""
    story_info = []
    is_story = False

    story_obj = getattr(message, "story", None)
    if story_obj:
        story_chat = getattr(getattr(story_obj, "chat", None), "title", "Unknown")
        story_username = getattr(getattr(story_obj, "chat", None), "username", "")
        story_info.append(f"Forwarded story from: {story_chat} (@{story_username})")
        is_story = True

    return story_info, is_story


def _collect_channel_info(message: types.Message) -> list[str]:
    """Collect information about channel senders."""
    channel_info = []

    if message.sender_chat and message.sender_chat.type == "channel":
        channel_title = message.sender_chat.title
        channel_username = (
            f" (@{message.sender_chat.username})"
            if message.sender_chat.username
            else ""
        )
        channel_info.append(f"Posted by channel: {channel_title}{channel_username}")

    return channel_info


def _combine_forward_info(message_text: str, forward_info: list[str]) -> str:
    """Combine message text with forward information if any exists."""
    if forward_info:
        return f"{message_text}\n[FORWARD_INFO]: {' | '.join(forward_info)}"
    return message_text


def extract_message_with_forward_context(message: types.Message) -> Tuple[str, bool]:
    """
    Extract message text and forwarding context for spam analysis.

    Analyzes the message to extract text content, forwarding information, channel context,
    and story indicators that help with spam classification. Combines all context
    information into the message text for LLM processing.

    Args:
        message: The message to analyze

    Returns:
        Tuple of (message_text, is_story) where message_text includes forward info
    """
    message_text = _extract_message_text(message)

    # Collect different types of forward/channel information
    forward_info = _collect_forward_info(message)
    story_info, is_story = _collect_story_info(message)
    channel_info = _collect_channel_info(message)

    # Combine all forward-related information
    all_forward_info = forward_info + story_info + channel_info

    # Add forward info to message text if any exists
    message_text = _combine_forward_info(message_text, all_forward_info)

    return message_text, is_story
