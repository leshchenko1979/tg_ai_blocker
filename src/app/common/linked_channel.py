from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import logfire
from aiogram import Bot

from .bot import bot
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
) -> Optional[LinkedChannelSummary]:
    with logfire.span(
        "Collecting linked channel summary via bot", user_reference=user_reference
    ):
        # Try bot extraction first
        bot_summary = await _collect_summary_via_bot(user_reference)
        if bot_summary is not None:
            return bot_summary

    logger.info(
        "Bot extraction failed, attempting MTProto fallback",
        extra={"user_reference": user_reference},
    )

    client = get_mtproto_client()
    with logfire.span(
        "Collecting linked channel summary via MTProto", user_reference=user_reference
    ):
        try:
            full_user_response = await client.call(
                "users.getFullUser", params={"id": user_reference}, resolve=True
            )
        except MtprotoHttpError as exc:
            logger.info(
                "MTProto failed for full user",
                extra={
                    "user_reference": user_reference,
                    "error": str(exc),
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

    with logfire.span(
        "Fetching linked channel via MTProto",
        user_reference=user_reference,
        channel_id=channel_id,
    ):
        try:
            full_channel = await client.call(
                "channels.getFullChannel", params={"channel": channel_id}, resolve=True
            )
        except MtprotoHttpError as exc:
            logger.info(
                "Failed to load full channel via MTProto",
                extra={
                    "user_reference": user_reference,
                    "channel_id": channel_id,
                    "error": str(exc),
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

    newest_message, total_posts = await _fetch_channel_edge_message(
        client, channel_id, limit_offset=None
    )

    newest_post_date = _extract_message_date(newest_message)
    oldest_post_date = None
    if total_posts and total_posts > 1:
        oldest_message, _ = await _fetch_channel_edge_message(
            client, channel_id, limit_offset=total_posts - 1
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
        "linked channel summary collected",
        source="mtproto",
        user_reference=user_reference,
        channel_id=channel_id,
        subscribers=subscribers,
        total_posts=total_posts,
        post_age_delta=post_age_delta,
    )

    return summary


async def _collect_summary_via_bot(
    user_reference: str | int,
    *,
    channel_id: Optional[int] = None,
    bot_client: Bot = bot,
) -> Optional[LinkedChannelSummary]:
    with logfire.span("Bot fallback: loading user chat", user_reference=user_reference):
        try:
            user_chat = await bot_client.get_chat(user_reference)
        except Exception as exc:  # noqa: BLE001
            logger.info(
                "Bot fallback failed to get user chat",
                extra={"user_reference": user_reference, "error": str(exc)},
            )
            return None

    personal_channel_id = channel_id or getattr(user_chat, "linked_chat_id", None)

    if not personal_channel_id:
        logfire.debug(
            "Bot fallback found no linked channel", user_reference=user_reference
        )
        return None

    with logfire.span(
        "Bot fallback: loading channel chat",
        user_reference=user_reference,
        channel_id=personal_channel_id,
    ):
        try:
            channel_chat = await bot_client.get_chat(personal_channel_id)
        except Exception as exc:  # noqa: BLE001
            logger.info(
                "Bot fallback failed to load channel chat",
                extra={
                    "user_reference": user_reference,
                    "channel_id": personal_channel_id,
                    "error": str(exc),
                },
            )
            return None

    subscribers = getattr(channel_chat, "members_count", None)

    logfire.debug(
        "Bot fallback channel stats",
        user_reference=user_reference,
        channel_id=personal_channel_id,
        subscribers=subscribers,
    )

    summary = LinkedChannelSummary(
        subscribers=subscribers,
        total_posts=None,
        post_age_delta=None,
    )

    logfire.info(
        "linked channel summary collected",
        source="bot",
        user_reference=user_reference,
        channel_id=personal_channel_id,
        subscribers=subscribers,
        total_posts=None,
        post_age_delta=None,
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
