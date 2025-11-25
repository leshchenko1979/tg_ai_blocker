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
        return "; ".join(parts)


@logfire.instrument()
async def collect_linked_channel_summary(
    user_reference: str | int,
    username: Optional[str] = None,
) -> Optional[LinkedChannelSummary]:
    client = get_mtproto_client()
    with logfire.span(
        "Collecting linked channel summary via MTProto (direct)",
        user_reference=user_reference,
        username=username,
    ):
        # Try username first if available, then fall back to user ID
        identifiers = []
        if username:
            identifiers.append(username)
        identifiers.append(user_reference)

        try:
            full_user_response, _ = await client.call_with_fallback(
                "users.getFullUser",
                identifiers=identifiers,
                identifier_param="id",
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
            return None

    full_user = full_user_response.get("full_user") or {}
    personal_channel_id = full_user.get("personal_channel_id")
    if not personal_channel_id:
        logfire.debug(
            "User has no linked channel in profile",
            user_reference=user_reference,
            full_user_keys=list(full_user.keys()),
        )
        return None

    channel_id = int(personal_channel_id)
    return await collect_channel_summary_by_id(channel_id, user_reference)


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
    if username:
        identifiers.append(username)

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

    newest_message, total_posts = await _fetch_channel_edge_message(
        client, peer_to_use, limit_offset=None
    )

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


def _extract_message_date(message: Optional[Dict[str, Any]]) -> Optional[datetime]:
    if not message:
        return None
    timestamp = message.get("date")
    if isinstance(timestamp, int):
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    if isinstance(timestamp, str):
        try:
            # Strings returned by the bridge are ISO8601 with timezone
            return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            logfire.debug("Failed to parse message date", timestamp=timestamp)
            return None
    return None
