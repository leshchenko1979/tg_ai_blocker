"""Logfire query utilities. get_weekly_stats for admin dashboard; message lookup is PostgreSQL."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Sequence

try:
    from logfire.query_client import LogfireQueryClient
except ImportError:
    raise ImportError(
        "logfire package is required for get_weekly_stats. Install with: pip install logfire"
    )

logger = logging.getLogger(__name__)

_client: LogfireQueryClient | None = None


def _get_client() -> LogfireQueryClient:
    """Get or create the LogfireQueryClient singleton."""
    global _client
    if _client is None:
        import os

        token = os.getenv("LOGFIRE_READ_TOKEN")
        if not token:
            raise ValueError(
                "LOGFIRE_READ_TOKEN environment variable is required for Logfire queries. "
                "Please set it to your Logfire read token."
            )
        _client = LogfireQueryClient(token)
    return _client


async def get_weekly_stats(chat_ids: Sequence[int]) -> Dict[int, Dict[str, int]]:
    """Query Logfire for weekly stats (last 7 days). Returns dict of chat_id -> {processed, spam}."""
    if not chat_ids:
        return {}

    start_time = datetime.now(timezone.utc) - timedelta(days=7)
    chat_ids_str = ", ".join(f"'{chat_id}'" for chat_id in chat_ids)

    # Tags indicating different outcomes
    spam_tags = {"spam_auto_deleted", "spam_admins_notified"}
    processed_tags = {
        "message_user_approved",
        "message_known_member_skipped",
        "message_insufficient_credits",
        "message_spam_check_failed",
        "message_from_group_admin_skipped",
        "message_from_channel_bot_skipped",
        "message_from_admin_skipped",
    } | spam_tags

    sql = f"""
    SELECT
        (attributes->'update'->'message'->'chat'->>'id')::bigint as chat_id,
        tags,
        count(*) as count
    FROM records
    WHERE
        start_timestamp >= '{start_time.isoformat()}'
        AND (attributes->'update'->'message'->'chat'->>'id')::bigint IN ({chat_ids_str})
    GROUP BY 1, 2
    """

    stats: Dict[int, Dict[str, int]] = {
        chat_id: {"processed": 0, "spam": 0} for chat_id in chat_ids
    }

    try:
        client = _get_client()
        results = await asyncio.to_thread(
            client.query_json_rows,
            sql=sql,
            min_timestamp=start_time,
        )

        if results and results.get("rows"):
            for row in results["rows"]:
                chat_id_val = row.get("chat_id")
                if chat_id_val is None:
                    continue
                chat_id = int(chat_id_val)

                tags = row.get("tags") or []
                count = int(row.get("count", 0))

                if chat_id not in stats:
                    continue

                # Check tags
                is_spam = any(t in spam_tags for t in tags)
                is_processed = any(t in processed_tags for t in tags)

                if is_spam:
                    stats[chat_id]["spam"] += count

                if is_processed:
                    stats[chat_id]["processed"] += count

        return stats

    except Exception as e:
        logger.warning(f"Failed to get weekly stats from Logfire: {e}", exc_info=True)
        return stats
