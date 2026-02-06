from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Generic, Optional, TypeVar

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

        # Include recent posts content if available
        if self.recent_posts_content:
            # Limit to first 3 posts and truncate each to 200 chars to avoid token bloat
            content_snippets = []
            for i, content in enumerate(self.recent_posts_content[:3]):
                if content.strip():
                    content_snippets.append(f"post_{i + 1}: {content.strip()}")

            if content_snippets:
                parts.append(f"recent_posts=[{'; '.join(content_snippets)}]")

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
class UserContext:
    stories: ContextResult[str]
    linked_channel: ContextResult[LinkedChannelSummary]
    account_info: ContextResult[UserAccountInfo]


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


@dataclass(slots=True)
class MessageAnalysisResult:
    """Result of message analysis containing all context data."""

    message_text: str
    is_story: bool
    bio: Optional[str]
    context: SpamClassificationContext


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
        return self.include_reply_guidance or self.include_stories_guidance or self.include_linked_channel_guidance
