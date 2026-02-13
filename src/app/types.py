from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar

from aiogram import types

from .common.utils import (
    determine_effective_user_id,
    format_chat_or_channel_display,
    sanitize_html,
)

T = TypeVar("T")


class ContextStatus(Enum):
    FOUND = "found"
    EMPTY = "empty"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ContextResult(Generic[T]):
    status: ContextStatus
    content: Optional[T] = None
    error: Optional[str] = None


@dataclass(slots=True)
class LinkedChannelSummary:
    subscribers: Optional[int]
    total_posts: Optional[int]
    post_age_delta: Optional[int]
    recent_posts_content: Optional[list[str]] = None
    users: Optional[list[dict]] = None
    channel_source: Optional[str] = None  # "linked" | "bio" | "message"
    channel_id: Optional[int] = None  # for display/resolve in /start etc.

    def to_prompt_fragment(self) -> str:
        if self.post_age_delta is None or self.post_age_delta < 0:
            post_age_str = "unknown"
        else:
            post_age_str = f"{self.post_age_delta}mo"

        parts = [
            f"subscribers={self.subscribers if self.subscribers is not None else 'unknown'}",
            f"total_posts={self.total_posts if self.total_posts is not None else 'unknown'}",
            f"age_delta={post_age_str}",
        ]
        if self.channel_source:
            parts.append(f"channel_source={self.channel_source}")

        # Include recent posts content if available
        if self.recent_posts_content:
            # Limit to first 3 posts and truncate each to 200 chars to avoid token bloat
            content_snippets = []
            for i, content in enumerate(self.recent_posts_content[:3]):
                if content.strip():
                    content_snippets.append(f"post_{i + 1}: {content.strip()}")

            if content_snippets:
                formatted_posts = "\n\n".join(content_snippets)
                parts.append(f"recent_posts=[\n{formatted_posts}\n]")

        return "; ".join(parts)


@dataclass(slots=True)
class UserAccountInfo:
    user_id: int
    profile_photo_date: Optional[datetime] = None

    @property
    def photo_age_months(self) -> Optional[int]:
        if not self.profile_photo_date:
            return None
        from datetime import timezone

        now = datetime.now(timezone.utc)
        return (
            (now.year - self.profile_photo_date.year) * 12
            + now.month
            - self.profile_photo_date.month
        )

    def to_prompt_fragment(self) -> str:
        parts = []

        # Only use photo age for prompt, ignore ID as per new robust strategy
        age_months = self.photo_age_months

        if age_months is not None:
            # Ensure non-negative
            age_months = max(0, age_months)
            parts.append(f"photo_age={age_months}mo")
        else:
            parts.append("photo_age=unknown")

        return "; ".join(parts)


@dataclass(slots=True)
class PeerResolutionContext:
    """Context information for MTProto peer resolution operations."""

    # Core identifiers (always required)
    chat_id: int
    user_id: int
    message_id: int

    # Optional context parameters
    chat_username: Optional[str] = None
    message_thread_id: Optional[int] = None
    reply_to_message_id: Optional[int] = None
    is_topic_message: bool = False
    main_channel_id: Optional[int] = None
    main_channel_username: Optional[str] = None
    original_channel_post_id: Optional[int] = None

    @classmethod
    def from_message(
        cls, message: types.Message, user_id: int
    ) -> PeerResolutionContext:
        """Create PeerResolutionContext from a Telegram message object."""
        chat_id = int(message.chat.id)
        message_id = int(message.message_id)
        chat_username = getattr(message.chat, "username", None)
        message_thread_id = getattr(message, "message_thread_id", None)
        is_topic_message = bool(getattr(message, "is_topic_message", False))

        main_channel_id = None
        main_channel_username = None

        if (
            message_thread_id
            and not is_topic_message
            and hasattr(message, "reply_to_message")
            and message.reply_to_message
        ):
            reply_to = message.reply_to_message
            if hasattr(reply_to, "sender_chat") and reply_to.sender_chat:
                sender_chat = reply_to.sender_chat
                if getattr(sender_chat, "type", None) == "channel":
                    main_channel_id = getattr(sender_chat, "id", None)
                    main_channel_username = getattr(sender_chat, "username", None)

        reply_to_message_id = None
        original_channel_post_id = None
        if hasattr(message, "reply_to_message") and message.reply_to_message:
            reply_to_message_id = getattr(message.reply_to_message, "message_id", None)
            if (
                hasattr(message, "message_thread_id")
                and message.message_thread_id
                and not getattr(message, "is_topic_message", False)
            ):
                original_channel_post_id = getattr(
                    message.reply_to_message, "forward_from_message_id", None
                )

        return cls(
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


@dataclass(slots=True)
class MessageContextResult:
    """Result of message context collection."""

    message_text: str
    is_story: bool
    context: "SpamClassificationContext"
    linked_channel_found: bool = False
    channel_users: Optional[list[dict]] = None


@dataclass(slots=True)
class SpamCheckResult:
    """Data class for spam check results."""

    chat_id: int
    user_id: int
    spam_score: float
    message_text: str
    bio: Optional[str]
    reason: Optional[str] = None


@dataclass
class SpamClassificationContext:
    """Context information for spam classification."""

    # Basic user info (always available from message)
    name: Optional[str] = None
    bio: Optional[str] = None

    # Enriched context (may require additional API calls)
    linked_channel: Optional[ContextResult[LinkedChannelSummary]] = None
    stories: Optional[ContextResult[str]] = None
    reply: Optional[str] = None
    account_age: Optional[ContextResult[UserAccountInfo]] = None
    is_channel_sender: bool = False

    @property
    def include_linked_channel_guidance(self) -> bool:
        """Whether to include linked channel guidance in the prompt."""
        return self.linked_channel is not None and self.linked_channel.status in (
            ContextStatus.FOUND,
            ContextStatus.EMPTY,
        )

    @property
    def include_stories_guidance(self) -> bool:
        """Whether to include stories guidance in the prompt."""
        return self.stories is not None and self.stories.status in (
            ContextStatus.FOUND,
            ContextStatus.EMPTY,
        )

    @property
    def include_reply_guidance(self) -> bool:
        """Whether to include reply context guidance in the prompt."""
        return self.reply is not None

    @property
    def include_account_age_guidance(self) -> bool:
        """Whether to include account age guidance in the prompt."""
        return self.account_age is not None and self.account_age.status in (
            ContextStatus.FOUND,
            ContextStatus.EMPTY,
        )

    @property
    def include_ai_detection_guidance(self) -> bool:
        """Whether to include AI and emoji detection guidance in the prompt."""
        # Always include if it's a reply, or if we want to be proactive
        return (
            self.include_reply_guidance
            or self.include_stories_guidance
            or self.include_linked_channel_guidance
        )


@dataclass
class StorySummary:
    id: int
    date: int
    caption: Optional[str] = None
    entities: Optional[List[Dict[str, Any]]] = None
    media: Optional[Dict[str, Any]] = None
    media_areas: Optional[List[Dict[str, Any]]] = None

    @staticmethod
    def _media_has_links_static(
        media: Optional[Dict[str, Any]],
        media_areas: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """Check if media or media_areas contain any links that should be included in context."""
        # Check media_areas first (these can be attached to any media type)
        if media_areas:
            for area in media_areas:
                if area.get("_") == "MediaAreaUrl" and area.get("url"):
                    return True

        if not media:
            return False

        media_type = media.get("_")
        if media_type == "messageMediaWebPage":
            webpage = media.get("webpage", {})
            return bool(webpage.get("url"))
        # Add other media types as needed

        return False

    def to_string(self) -> str:
        parts = []
        if self.caption:
            parts.append(f"Caption: {self.caption}")
        if self.entities:
            links = []
            for entity in self.entities:
                if entity.get("_") == "messageEntityTextUrl":
                    links.append(f"Link: {entity.get('url')}")
                elif entity.get("_") == "messageEntityUrl":
                    # URL is likely in the text/caption itself, but good to note
                    pass
            if links:
                parts.append(f"Links: {', '.join(links)}")

        # Extract links from media (e.g., webpage URLs, document links)
        if self.media:
            media_links = []
            media_type = self.media.get("_")

            if media_type == "messageMediaWebPage":
                webpage = self.media.get("webpage", {})
                if webpage.get("url"):
                    media_links.append(f"Link: {webpage['url']}")
            elif media_type == "messageMediaDocument":
                # Check for media areas with URLs
                media_areas = self.media.get("media_areas", [])
                for area in media_areas:
                    if area.get("_") == "MediaAreaUrl" and area.get("url"):
                        media_links.append(f"Link: {area['url']}")
                # Could also check document attributes for links, but focus on media areas for now
            # Add other media types as needed

            if media_links:
                parts.append(f"Links: {', '.join(media_links)}")

        # Extract links from media areas (clickable areas on media)
        if self.media_areas:
            area_links = []
            for area in self.media_areas:
                if area.get("_") == "MediaAreaUrl" and area.get("url"):
                    area_links.append(f"Link: {area['url']}")

            if area_links:
                parts.append(f"Links: {', '.join(area_links)}")

        return " | ".join(parts) if parts else "Media story"


@dataclass(slots=True)
class MessageNotificationContext:
    effective_user_id: Optional[int]
    content_text: str
    chat_title: str
    chat_username: Optional[str]  # raw username without @
    is_channel_sender: bool
    violator_name: str
    violator_username: Optional[str]  # raw username without @
    forward_source: str
    message_link: str
    entity_name: str
    entity_type: str
    entity_username: Optional[str]  # raw username without @

    @classmethod
    def from_message(cls, message: types.Message) -> MessageNotificationContext:
        """Create MessageNotificationContext from a Telegram message."""
        effective_user_id = determine_effective_user_id(message)
        content_text = message.text or message.caption or "[MEDIA_MESSAGE]"
        content_text = sanitize_html(content_text)
        chat_title = message.chat.title or "Группа"
        chat_username = getattr(message.chat, "username", None)
        is_channel_sender = (
            message.sender_chat is not None
            and message.sender_chat.id != message.chat.id
        )

        if is_channel_sender and message.sender_chat is not None:
            violator_name = message.sender_chat.title or "Канал"
            violator_username = getattr(message.sender_chat, "username", None)
        elif message.from_user is not None:
            violator_name = message.from_user.full_name or "Пользователь без имени"
            violator_username = getattr(message.from_user, "username", None)
        else:
            violator_name = "Пользователь"
            violator_username = None

        forward_source = ""
        forward_chat = getattr(message, "forward_from_chat", None)
        if forward_chat:
            forward_title = getattr(forward_chat, "title", None) or "Канал"
            forward_username = getattr(forward_chat, "username", None)
            forward_source = (
                "\n\n"
                f"<b>Источник пересланного:</b> "
                f"{format_chat_or_channel_display(forward_title, forward_username, 'Канал')}"
            )

        message_link = (
            f"https://t.me/{message.chat.username}/{message.message_id}"
            if message.chat.username
            else ""
        )

        reply_sender_chat = None
        if message.reply_to_message is not None:
            reply_sender_chat = getattr(message.reply_to_message, "sender_chat", None)

        if reply_sender_chat is not None:
            entity_name = reply_sender_chat.title or "Канал"
            entity_type = "канале"
            entity_username = getattr(reply_sender_chat, "username", None)
        else:
            entity_name = chat_title
            entity_type = "группе"
            entity_username = chat_username

        return cls(
            effective_user_id=effective_user_id,
            content_text=content_text,
            chat_title=chat_title,
            chat_username=chat_username,
            is_channel_sender=is_channel_sender,
            violator_name=violator_name,
            violator_username=violator_username,
            forward_source=forward_source,
            message_link=message_link,
            entity_name=entity_name,
            entity_type=entity_type,
            entity_username=entity_username,
        )
