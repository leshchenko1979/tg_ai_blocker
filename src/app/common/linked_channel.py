from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import logfire

from .mtproto_client import MtprotoHttpClient, MtprotoHttpError, get_mtproto_client

logger = logging.getLogger(__name__)


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
                    truncated = content[:200].strip()
                    if len(content) > 200:
                        truncated += "..."
                    content_snippets.append(f"post_{i + 1}: {truncated}")

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
    linked_channel: Optional[LinkedChannelSummary] = None
    account_info: Optional[UserAccountInfo] = None


@logfire.instrument()
async def collect_user_context(
    user_reference: str | int,
    username: Optional[str] = None,
) -> UserContext:
    """
    Collects user context including linked channel summary and account age signals.
    """
    client = get_mtproto_client()
    linked_channel_summary = None
    account_info = None

    with logfire.span(
        "Collecting user context via MTProto",
        user_reference=user_reference,
        username=username,
    ):
        # Only use username for peer resolution (numeric IDs almost always fail)
        if not username:
            logfire.debug("No username available, skipping user context collection")
            return UserContext()

        identifiers = [username]

        full_user = {}
        try:
            full_user_response, _ = await client.call_with_fallback(
                "users.getFullUser",
                identifiers=identifiers,
                identifier_param="id",
            )
            full_user = full_user_response.get("full_user") or {}

            # Extract Account Info
            user_id = full_user.get("id")
            if not user_id and isinstance(user_reference, int):
                user_id = user_reference

            # Fallback to user_reference if int and not found in response (unlikely for success)
            if user_id:
                profile_photo = full_user.get("profile_photo")
                photo_date = None
                if profile_photo and isinstance(profile_photo, dict):
                    photo_date = _extract_date(profile_photo.get("date"))

                account_info = UserAccountInfo(
                    user_id=int(user_id),
                    profile_photo_date=photo_date,
                )

        except MtprotoHttpError as e:
            logger.info(
                "MTProto failed for full user with all identifiers",
                extra={
                    "user_reference": user_reference,
                    "username": username,
                    "identifiers_tried": identifiers,
                    "error": str(e),
                },
            )
            # Proceed without full user info (returns empty context)
            pass

        # Extract Linked Channel
        personal_channel_id = full_user.get("personal_channel_id")
        if personal_channel_id:
            channel_id = int(personal_channel_id)
            linked_channel_summary = await collect_channel_summary_by_id(
                channel_id, user_reference
            )
        else:
            logfire.debug(
                "User has no linked channel in profile",
                user_reference=user_reference,
                full_user_keys=list(full_user.keys()),
            )

    return UserContext(linked_channel=linked_channel_summary, account_info=account_info)


# Alias for backward compatibility if needed, but we will refactor usage
collect_linked_channel_summary = collect_user_context


@logfire.instrument()
async def collect_channel_summary_by_id(
    channel_id: int,
    user_reference: str | int = "unknown",
    username: Optional[str] = None,
) -> Optional[LinkedChannelSummary]:
    """
    Collects summary stats for a specific channel ID.
    Reuses logic previously embedded in collect_linked_channel_summary.
    """
    client = get_mtproto_client()

    identifiers = []

    # Prefer username for channel resolution if available
    if username:
        identifiers.append(username)
    else:
        # Convert Bot API ID (negative -100...) to MTProto ID (positive, without -100)
        mtproto_id = channel_id
        if channel_id < 0:
            str_id = str(channel_id)
            if str_id.startswith("-100"):
                mtproto_id = int(str_id[4:])
            elif str_id.startswith("-"):
                mtproto_id = int(str_id[1:])
        identifiers.append(mtproto_id)

    with logfire.span(
        "Fetching channel summary via MTProto",
        user_reference=user_reference,
        channel_id=channel_id,
        username=username,
    ):
        try:
            full_channel, successful_identifier = await client.call_with_fallback(
                "channels.getFullChannel",
                identifiers=identifiers,
                identifier_param="channel",
            )
        except MtprotoHttpError as e:
            logger.info(
                "Failed to load full channel via MTProto",
                extra={
                    "user_reference": user_reference,
                    "channel_id": channel_id,
                    "username": username,
                    "identifiers_tried": identifiers,
                    "error": str(e),
                },
            )
            return None

    subscribers = full_channel.get("full_chat", {}).get("participants_count")
    logfire.debug(
        "MTProto channel stats",
        user_reference=user_reference,
        channel_id=channel_id,
        subscribers=subscribers,
    )

    # Use the identifier that worked for the history call to ensure consistency
    peer_to_use = successful_identifier

    # Fetch recent posts content for spam analysis - this also gives us the newest message and total count
    (
        recent_posts_content,
        newest_message,
        total_posts,
    ) = await _fetch_recent_posts_content(client, peer_to_use, limit=5)

    newest_post_date = _extract_message_date(newest_message)
    oldest_post_date = None
    if total_posts and total_posts > 1:
        oldest_message, _ = await _fetch_channel_edge_message(
            client, peer_to_use, limit_offset=total_posts - 1
        )
        oldest_post_date = _extract_message_date(oldest_message)

    oldest_post_date = oldest_post_date or newest_post_date
    post_age_delta = None
    if newest_post_date and oldest_post_date:
        delta_days = (newest_post_date - oldest_post_date).days
        post_age_delta = max(delta_days // 30, 0)

    summary = LinkedChannelSummary(
        subscribers=subscribers,
        total_posts=total_posts,
        post_age_delta=post_age_delta,
        recent_posts_content=recent_posts_content if recent_posts_content else None,
    )

    logfire.info(
        "channel summary collected",
        source="mtproto",
        user_reference=user_reference,
        channel_id=channel_id,
        subscribers=subscribers,
        total_posts=total_posts,
        post_age_delta=post_age_delta,
    )

    return summary


@logfire.instrument()
async def _fetch_channel_edge_message(
    client: MtprotoHttpClient,
    peer_reference: int | str,
    *,
    limit_offset: Optional[int],
) -> tuple[Optional[Dict[str, Any]], Optional[int]]:
    params: Dict[str, Any] = {
        "peer": peer_reference,
        "offset_id": 0,
        "offset_date": 0,
        "add_offset": max(limit_offset or 0, 0),
        "limit": 1,
        "max_id": 0,
        "min_id": 0,
        "hash": 0,
    }

    try:
        history = await client.call("messages.getHistory", params=params, resolve=True)
    except MtprotoHttpError as exc:
        logger.info(
            "Failed to fetch channel history",
            extra={"peer_reference": peer_reference, "error": str(exc)},
        )
        return None, None

    messages = history.get("messages", [])
    message = messages[0] if messages else None
    total = history.get("count")
    if total is None and messages:
        total = len(messages)
    return message, total


@logfire.instrument()
async def _fetch_recent_posts_content(
    client: MtprotoHttpClient,
    peer_reference: int | str,
    limit: int = 5,
) -> tuple[list[str], Optional[Dict[str, Any]], Optional[int]]:
    """
    Fetch content from recent posts in a channel to analyze for spam indicators.
    Returns tuple of (content_list, newest_message, total_count).
    - content_list: list of text content from recent posts (excluding media-only posts)
    - newest_message: the most recent message (first in results)
    - total_count: total number of messages in the channel
    """
    params: Dict[str, Any] = {
        "peer": peer_reference,
        "offset_id": 0,
        "offset_date": 0,
        "add_offset": 0,
        "limit": limit,
        "max_id": 0,
        "min_id": 0,
        "hash": 0,
    }

    try:
        history = await client.call("messages.getHistory", params=params, resolve=True)
    except MtprotoHttpError as exc:
        logger.info(
            "Failed to fetch recent posts content",
            extra={"peer_reference": peer_reference, "error": str(exc)},
        )
        return [], None, None

    messages = history.get("messages", [])
    content_list = []
    newest_message = messages[0] if messages else None
    total_count = history.get("count")

    for message in messages:
        # Extract text content from message
        text_content = _extract_message_text(message)
        if text_content and text_content.strip():
            content_list.append(text_content.strip())

    return content_list, newest_message, total_count


def _extract_message_text(message: Dict[str, Any]) -> str:
    """Extract text content from a Telegram message."""
    if not message:
        return ""

    # Direct message text
    message_text = message.get("message", "")

    # Caption from media messages
    if not message_text:
        media = message.get("media")
        if media and isinstance(media, dict):
            message_text = media.get("caption", "")

    return message_text


def _extract_date(timestamp: Any) -> Optional[datetime]:
    if not timestamp:
        return None
    if isinstance(timestamp, int):
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    if isinstance(timestamp, str):
        try:
            # Strings returned by the bridge are ISO8601 with timezone
            return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            logfire.debug("Failed to parse date", timestamp=timestamp)
            return None
    return None


def _extract_message_date(message: Optional[Dict[str, Any]]) -> Optional[datetime]:
    if not message:
        return None
    return _extract_date(message.get("date"))
