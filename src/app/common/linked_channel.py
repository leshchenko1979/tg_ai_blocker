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
    title: Optional[str]
    username: Optional[str]
    invite_link: Optional[str]
    subscribers: Optional[int]
    total_posts: Optional[int]
    newest_post_date: Optional[datetime]
    oldest_post_date: Optional[datetime]
    post_age_delta: Optional[int]
    newest_post_preview: Optional[str]

    def to_prompt_fragment(self) -> str:
        from datetime import datetime

        def months_ago(dt: Optional[datetime]) -> str:
            if not dt:
                return "unknown"
            now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now(timezone.utc)
            # Calculate months difference (approximate: 30 days per month)
            delta_days = (now - dt).days
            months = delta_days // 30
            return f"{months}mo ago" if months >= 0 else "unknown"

        def months_delta(delta_seconds: Optional[int]) -> str:
            if delta_seconds is None:
                return "unknown"
            months = delta_seconds // (30 * 24 * 60 * 60)
            return f"{months}mo" if months >= 0 else "unknown"

        parts = [
            f"title={self.title or 'unknown'}",
            f"username={self.username or 'unknown'}",
            f"invite_link={self.invite_link or 'n/a'}",
            f"subscribers={self.subscribers if self.subscribers is not None else 'unknown'}",
            f"total_posts={self.total_posts if self.total_posts is not None else 'unknown'}",
            f"newest_post={months_ago(self.newest_post_date)}",
            f"oldest_post={months_ago(self.oldest_post_date)}",
            f"age_delta={months_delta(self.post_age_delta)}",
        ]

        preview = self.newest_post_preview.strip() if self.newest_post_preview else None
        if preview:
            preview = preview[:400]
            parts.append(f"latest_post_preview={preview}")

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

    channel = _locate_channel(full_user_response.get("chats", []), personal_channel_id)
    if not channel:
        logger.warning(
            "Linked channel not found in users.getFullUser response",
            extra={
                "user_reference": user_reference,
                "resolved_user": resolved_user,
                "personal_channel_id": personal_channel_id,
            },
        )
        return None

    channel_id = channel.get("id")
    if channel_id is None:
        logger.warning(
            "Linked channel lacks id",
            extra={
                "user_reference": user_reference,
                "resolved_user": resolved_user,
                "channel": channel,
            },
        )
        return None

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

    chat_meta = _find_chat_meta(full_channel, channel_id)
    invite_link = _extract_invite_link(full_channel)
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

    newest_preview = _extract_message_preview(newest_message)

    return LinkedChannelSummary(
        title=chat_meta.get("title") if chat_meta else None,
        username=chat_meta.get("username") if chat_meta else None,
        invite_link=invite_link,
        subscribers=subscribers,
        total_posts=total_posts,
        newest_post_date=newest_post_date,
        oldest_post_date=oldest_post_date,
        post_age_delta=post_age_delta,
        newest_post_preview=newest_preview,
    )


def _locate_channel(
    chats: list[Dict[str, Any]], personal_channel_id: int
) -> Optional[Dict[str, Any]]:
    candidates: Dict[int, Dict[str, Any]] = {}
    for chat in chats or []:
        chat_id = chat.get("id")
        if chat_id is not None:
            candidates[int(chat_id)] = chat

    if not candidates:
        return None

    channel_id = int(personal_channel_id)
    if channel_id in candidates:
        return candidates[channel_id]

    # MTProto channel ids often use lower 32-bits for matching.
    reduced_id = channel_id & 0xFFFFFFFF
    if reduced_id in candidates:
        return candidates[reduced_id]

    return None


def _find_chat_meta(response: Dict[str, Any], channel_id: int) -> Dict[str, Any]:
    chats = response.get("chats", [])
    if not chats:
        return {}

    for chat in chats:
        if chat.get("id") == channel_id:
            return chat

    reduced_id = channel_id & 0xFFFFFFFF
    for chat in chats:
        if chat.get("id") == reduced_id:
            return chat
    return {}


def _extract_invite_link(response: Dict[str, Any]) -> Optional[str]:
    full_chat = response.get("full_chat", {})
    exported_invite = full_chat.get("exported_invite")
    if isinstance(exported_invite, dict):
        return exported_invite.get("link")
    return None


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


def _extract_message_preview(message: Optional[Dict[str, Any]]) -> Optional[str]:
    if not message:
        return None
    text = message.get("message")
    if text:
        return text
    media_caption = (
        message.get("media", {}).get("caption")
        if isinstance(message.get("media"), dict)
        else None
    )
    if media_caption:
        return media_caption
    return None
