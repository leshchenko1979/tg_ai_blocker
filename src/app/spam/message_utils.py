"""
Utilities for extracting and processing Telegram message data.

This module provides functions for parsing Telegram message objects
and extracting relevant metadata for spam detection context collection.
"""

from typing import Any, Dict, Optional


def extract_message_metadata(message) -> Dict[str, Any]:
    """
    Extract metadata from a Telegram message object for context collection.

    Args:
        message: Telegram message object

    Returns:
        Dict containing extracted message metadata
    """
    return {
        "chat_id": message.chat.id,
        "message_id": getattr(message, "message_id", None),
        "chat_username": getattr(message.chat, "username", None),
        "message_thread_id": getattr(message, "message_thread_id", None),
        "is_topic_message": getattr(message, "is_topic_message", False),
        "linked_chat_id": getattr(message.chat, "linked_chat_id", None),
        "reply_to_message_id": None,
        "original_channel_post_id": None,
    }


def extract_reply_metadata(message) -> Dict[str, Optional[int]]:
    """
    Extract reply-related metadata from a message.

    Args:
        message: Telegram message object

    Returns:
        Dict with reply_to_message_id and original_channel_post_id
    """
    metadata = {
        "reply_to_message_id": None,
        "original_channel_post_id": None,
    }

    if hasattr(message, "reply_to_message") and message.reply_to_message:
        metadata["reply_to_message_id"] = getattr(
            message.reply_to_message, "message_id", None
        )
        # For discussion threads, get the original channel post ID from the forwarded message
        if (
            hasattr(message, "message_thread_id")
            and message.message_thread_id
            and not getattr(message, "is_topic_message", False)
        ):
            metadata["original_channel_post_id"] = getattr(
                message.reply_to_message, "forward_from_message_id", None
            )

    return metadata


def merge_message_metadata(
    message_meta: Dict[str, Any], reply_meta: Dict[str, Optional[int]]
) -> Dict[str, Any]:
    """
    Merge message metadata dictionaries into a single context dict.

    Args:
        message_meta: Metadata from extract_message_metadata
        reply_meta: Metadata from extract_reply_metadata

    Returns:
        Combined metadata dictionary
    """
    return {**message_meta, **reply_meta}
