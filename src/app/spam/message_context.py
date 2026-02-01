"""
Message context collection and spam analysis.

This module handles the extraction of context information from messages
and performs spam analysis using the collected context.
"""

import logging
from typing import Optional, Tuple, Union

from aiogram import types

from ..spam.context_types import (
    MessageAnalysisResult,
    SpamClassificationContext,
    UserContext,
)
from .context_collector import route_sender_context_collection

logger = logging.getLogger(__name__)


async def collect_message_context(
    message: types.Message,
) -> MessageAnalysisResult:
    """
    Collect all relevant context data for message analysis.

    This function focuses solely on data collection and does not perform
    the actual spam classification.

    Args:
        message: The Telegram message to analyze

    Returns:
        MessageAnalysisResult containing all context data
    """
    message_text, is_story = build_forward_info(message)

    reply_context = extract_reply_context(message)
    sender_context, name, bio = await route_sender_context_collection(
        message, message.chat.id
    )

    context = create_classification_context(sender_context, name, bio, reply_context)

    return MessageAnalysisResult(message_text, is_story, bio, context)


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


def build_forward_info(message: types.Message) -> Tuple[str, bool]:
    """
    Build information about forwards, channels, and stories for a message.

    Analyzes the message to extract forwarding information, channel context,
    and story indicators that help with spam classification.

    Args:
        message: The message to analyze

    Returns:
        Tuple of (message_text, is_story)
    """
    message_text = message.text or message.caption or "[MEDIA_MESSAGE]"
    forward_info = []
    is_story = False

    if message.forward_from:
        forward_info.append(f"Forwarded from user: {message.forward_from.full_name}")

    if message.forward_from_chat:
        forward_info.append(f"Forwarded from chat: {message.forward_from_chat.title}")

    story_obj = getattr(message, "story", None)

    if story_obj:
        story_chat = getattr(getattr(story_obj, "chat", None), "title", "Unknown")
        story_username = getattr(getattr(story_obj, "chat", None), "username", "")
        forward_info.append(f"Forwarded story from: {story_chat} (@{story_username})")
        is_story = True

    if message.sender_chat and message.sender_chat.type == "channel":
        channel_title = message.sender_chat.title
        channel_username = (
            f" (@{message.sender_chat.username})"
            if message.sender_chat.username
            else ""
        )
        forward_info.append(f"Posted by channel: {channel_title}{channel_username}")

    if forward_info:
        message_text = f"{message_text}\n[FORWARD_INFO]: {' | '.join(forward_info)}"

    return message_text, is_story
