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
    newest_post_date: Optional[datetime]
    oldest_post_date: Optional[datetime]
    post_age_delta: Optional[int]

    def to_prompt_fragment(self) -> str:
        def months_delta(delta_seconds: Optional[int]) -> str:
            if delta_seconds is None:
                return "unknown"
            months = delta_seconds // (30 * 24 * 60 * 60)
            return f"{months}mo" if months >= 0 else "unknown"

        parts = [
            f"subscribers={self.subscribers if self.subscribers is not None else 'unknown'}",
            f"total_posts={self.total_posts if self.total_posts is not None else 'unknown'}",
            f"age_delta={months_delta(self.post_age_delta)}",
        ]
        return "; ".join(parts)


@logfire.instrument()
async def collect_linked_channel_summary(
    user_reference: str | int,
) -> Optional[LinkedChannelSummary]:
    client = get_mtproto_client()
    try:
        full_user_response = await client.call(
            "users.getFullUser", params={"id": user_reference}, resolve=True
        )
    except MtprotoHttpError as exc:
        logger.info(
            "Failed to load full user",
            extra={
                "user_reference": user_reference,
                "error": str(exc),
            },
        )
        return None

    resolved_user = None
    users_block = full_user_response.get("users") or []
    if users_block:
        resolved_user = users_block[0]

    full_user = full_user_response.get("full_user") or {}
    personal_channel_id = full_user.get("personal_channel_id")
    if not personal_channel_id:
        logger.debug(
            "User has no linked channel in profile",
            extra={
                "user_reference": user_reference,
                "resolved_user": resolved_user,
                "full_user_keys": list(full_user.keys()),
            },
        )
        return None

    channel_id = int(personal_channel_id)

    try:
        full_channel = await client.call(
            "channels.getFullChannel", params={"channel": channel_id}, resolve=True
        )
    except MtprotoHttpError as exc:
        logger.info(
            "Failed to load full channel",
            extra={
                "user_reference": user_reference,
                "resolved_user": resolved_user,
                "channel_id": channel_id,
                "error": str(exc),
            },
        )
        return None

    subscribers = full_channel.get("full_chat", {}).get("participants_count")

    newest_message, total_posts = await _fetch_channel_edge_message(
        client, channel_id, limit_offset=None
    )

    oldest_message = None
    if total_posts and total_posts > 1:
        oldest_message, _ = await _fetch_channel_edge_message(
            client, channel_id, limit_offset=total_posts - 1
        )

    newest_post_date = _extract_message_date(newest_message)
    oldest_post_date = _extract_message_date(oldest_message) or newest_post_date

    post_age_delta = None
    if newest_post_date and oldest_post_date:
        post_age_delta = int((newest_post_date - oldest_post_date).total_seconds())

    return LinkedChannelSummary(
        subscribers=subscribers,
        total_posts=total_posts,
        newest_post_date=newest_post_date,
        oldest_post_date=oldest_post_date,
        post_age_delta=post_age_delta,
    )


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
            logger.debug("Failed to parse message date", extra={"timestamp": timestamp})
            return None
    return None
