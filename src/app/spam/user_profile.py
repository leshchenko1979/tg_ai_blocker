from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import logfire

from .context_types import (
    ContextResult,
    ContextStatus,
    LinkedChannelSummary,
    UserAccountInfo,
    UserContext,
)
from ..common.mtproto_client import (
    MtprotoHttpClient,
    MtprotoHttpError,
    get_mtproto_client,
)

logger = logging.getLogger(__name__)


@logfire.instrument()
async def collect_user_context(
    user_reference: str | int,
    username: Optional[str] = None,
    chat_id: Optional[int] = None,
) -> UserContext:
    """
    Collects user context including linked channel summary and account age signals.
    """
    client = get_mtproto_client()
    linked_channel_result = ContextResult(status=ContextStatus.EMPTY)
    account_info_result = ContextResult(status=ContextStatus.EMPTY)

    with logfire.span(
        "Collecting user context via MTProto",
        user_reference=user_reference,
        username=username,
        chat_id=chat_id,
    ):
        # Set up identifier: prefer username, but use user_id if no username
        # (subscription check is handled at higher level)
        if username:
            identifier = username
        else:
            # Using user_id directly (subscription already verified at higher level)
            user_id = user_reference if isinstance(user_reference, int) else None
            if not user_id:
                logfire.error(
                    "No username and invalid user_reference for user_id-based collection"
                )
                return UserContext(
                    stories=ContextResult(
                        status=ContextStatus.FAILED,
                        error="Invalid user reference for user_id-based collection",
                    ),
                    linked_channel=ContextResult(
                        status=ContextStatus.FAILED,
                        error="Invalid user reference for user_id-based collection",
                    ),
                    account_info=ContextResult(
                        status=ContextStatus.FAILED,
                        error="Invalid user reference for user_id-based collection",
                    ),
                )
            identifier = user_id

        full_user = {}
        try:
            full_user_response = await client.call(
                "users.getFullUser",
                params={"id": identifier},
                resolve=True,
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

                account_info_result = ContextResult(
                    status=ContextStatus.FOUND,
                    content=UserAccountInfo(
                        user_id=int(user_id),
                        profile_photo_date=photo_date,
                    ),
                )
            else:
                account_info_result = ContextResult(status=ContextStatus.EMPTY)

        except MtprotoHttpError as e:
            logger.info(
                "MTProto failed for full user",
                extra={
                    "user_reference": user_reference,
                    "username": username,
                    "identifier_used": identifier,
                    "error": str(e),
                },
            )
            account_info_result = ContextResult(
                status=ContextStatus.FAILED, error=str(e)
            )

        # Extract Linked Channel
        personal_channel_id = full_user.get("personal_channel_id")
        if personal_channel_id:
            channel_id = int(personal_channel_id)
            channel_result = await collect_channel_summary_by_id(
                channel_id, user_reference
            )
            linked_channel_result = channel_result
        else:
            logfire.debug(
                "User has no linked channel in profile",
                user_reference=user_reference,
                full_user_keys=list(full_user.keys()),
            )
            linked_channel_result = ContextResult(status=ContextStatus.EMPTY)

    # Stories will be collected separately, so we return SKIPPED for now
    return UserContext(
        stories=ContextResult(
            status=ContextStatus.SKIPPED, error="Stories collected separately"
        ),
        linked_channel=linked_channel_result,
        account_info=account_info_result,
    )


@logfire.instrument()
async def collect_channel_summary_by_id(
    channel_id: int,
    user_reference: str | int = "unknown",
    username: Optional[str] = None,
) -> ContextResult[LinkedChannelSummary]:
    """
    Collects summary stats for a specific channel ID.
    """
    client = get_mtproto_client()

    # Use username if available, otherwise convert Bot API ID to MTProto format
    if username:
        channel_identifier = username
    else:
        # Convert Bot API ID (negative -100...) to MTProto ID (positive, without -100)
        mtproto_id = channel_id
        if channel_id < 0:
            str_id = str(channel_id)
            if str_id.startswith("-100"):
                mtproto_id = int(str_id[4:])
            elif str_id.startswith("-"):
                mtproto_id = int(str_id[1:])
        channel_identifier = mtproto_id

    with logfire.span(
        "Fetching channel summary via MTProto",
        user_reference=user_reference,
        channel_id=channel_id,
        username=username,
    ):
        try:
            full_channel = await client.call(
                "channels.getFullChannel",
                params={"channel": channel_identifier},
                resolve=True,
            )
        except MtprotoHttpError as e:
            logger.info(
                "Failed to load full channel via MTProto",
                extra={
                    "user_reference": user_reference,
                    "channel_id": channel_id,
                    "username": username,
                    "identifier_used": channel_identifier,
                    "error": str(e),
                },
            )
            return ContextResult(status=ContextStatus.FAILED, error=str(e))

    subscribers = full_channel.get("full_chat", {}).get("participants_count")
    logfire.debug(
        "MTProto channel stats",
        user_reference=user_reference,
        channel_id=channel_id,
        subscribers=subscribers,
    )

    # Use the identifier that worked for the history call to ensure consistency
    peer_to_use = channel_identifier

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

    return ContextResult(status=ContextStatus.FOUND, content=summary)


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
