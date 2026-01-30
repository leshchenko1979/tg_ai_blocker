"""
Message context collection and spam analysis.

This module handles the extraction of context information from messages
and performs spam analysis using the collected context.
"""

import logging
from typing import Optional, Tuple, Union

from aiogram import types

from ..common.bot import bot
from ..common.tracking import track_group_event
from ..database.models import Group
from ..spam.context_types import SpamClassificationContext, UserContext
from ..spam.spam_classifier import is_spam
from .context_collector import route_sender_context_collection

logger = logging.getLogger(__name__)


async def analyze_message_content(
    message: types.Message, group: Group
) -> Tuple[Optional[float], Optional[str], str, bool, str]:
    """
    Analyze message content for spam.

    Args:
        message: The Telegram message to analyze
        group: The group object containing moderation settings

    Returns:
        Tuple of (spam_score, bio, reason, is_story, message_text)
    """
    message_text, forward_info, is_story = build_forward_info(message)
    spam_score, bio, reason = await get_spam_score_and_bio(
        message, message_text, group, is_story
    )
    return spam_score, bio, reason, is_story, message_text


async def get_spam_score_and_bio(
    message: types.Message, message_text: str, group: Group, is_story: bool
) -> Tuple[Optional[float], Optional[str], str]:
    """
    Get spam score and user bio for message analysis.

    Args:
        message: The message to analyze
        message_text: The processed message text
        group: The group object with admin IDs
        is_story: Whether this is a story forward

    Returns:
        Tuple of (spam_score, bio, reason)
    """
    if is_story:
        return 100, None, "Story forward"

    reply_context = extract_reply_context(message)
    sender_context = await route_sender_context_collection(message, message.chat.id)

    name, bio = await get_sender_info(message, sender_context)
    context = create_classification_context(sender_context, name, bio, reply_context)

    spam_score, reason = await is_spam(
        comment=message_text,
        admin_ids=group.admin_ids,
        context=context,
    )
    return spam_score, bio, reason


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


async def get_sender_info(
    message: types.Message,
    sender_context: Union[UserContext, SpamClassificationContext],
) -> Tuple[str, Optional[str]]:
    """
    Get sender name and bio based on context type.

    Args:
        message: The message from the sender
        sender_context: The context object (UserContext or SpamClassificationContext)

    Returns:
        Tuple of (name, bio)
    """
    if isinstance(sender_context, UserContext):
        name = message.from_user.full_name if message.from_user else "Unknown"
        bio = await get_user_bio(message.from_user.id) if message.from_user else None
        return name, bio
    elif isinstance(sender_context, SpamClassificationContext):
        name = sender_context.name or "Channel"
        bio = sender_context.bio
        return name, bio

    return "Unknown", None


async def get_user_bio(user_id: int) -> Optional[str]:
    """
    Get user bio from Telegram API.

    Args:
        user_id: The user ID to get bio for

    Returns:
        User bio if available, None otherwise
    """
    try:
        user_with_bio = await bot.get_chat(user_id)
        return user_with_bio.bio if user_with_bio else None
    except Exception:
        return None


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


async def track_spam_check_result(
    chat_id: int,
    user_id: int,
    spam_score: float,
    message_text: str,
    bio: Optional[str],
    reason: Optional[str] = None,
) -> None:
    """
    Track the result of spam analysis for analytics.

    Args:
        chat_id: The chat ID where analysis occurred
        user_id: The user ID being analyzed
        spam_score: The calculated spam score
        message_text: The message content for analytics tracking
        bio: User bio information
        reason: Classification reason
    """
    await track_group_event(
        chat_id,
        "spam_check_result",
        {
            "chat_id": chat_id,
            "user_id": user_id,
            "spam_score": spam_score,
            "is_spam": spam_score > 50,
            "message_text": message_text,
            "user_bio": bio,
            "reason": reason,
        },
    )


def build_forward_info(message: types.Message) -> Tuple[str, list[str], bool]:
    """
    Build information about forwards, channels, and stories for a message.

    Analyzes the message to extract forwarding information, channel context,
    and story indicators that help with spam classification.

    Args:
        message: The message to analyze

    Returns:
        Tuple of (message_text, forward_info, is_story)
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

    return message_text, forward_info, is_story
