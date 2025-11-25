import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, Sequence

try:
    from logfire.query_client import LogfireQueryClient
except ImportError:
    raise ImportError(
        "logfire package is required for message lookup. "
        "Install with: pip install logfire"
    )

logger = logging.getLogger(__name__)

# Module-level client for reuse
_client: Optional[LogfireQueryClient] = None


def _get_client() -> LogfireQueryClient:
    """Get or create the LogfireQueryClient singleton."""
    global _client
    if _client is None:
        token = os.getenv("LOGFIRE_READ_TOKEN")
        if not token:
            raise ValueError(
                "LOGFIRE_READ_TOKEN environment variable is required for message lookup. "
                "Please set it to your Logfire read token."
            )
        _client = LogfireQueryClient(token)
    return _client


async def find_original_message(
    user_id: Optional[int],
    message_text: str,
    forward_date: datetime,
    admin_chat_ids: Sequence[int],
    search_days_back: int = 3,
) -> Optional[Dict[str, int]]:
    """
    Query Logfire to find the original message by user_id (if available), text, and date.

    Args:
        user_id: The ID of the user who sent the original message (optional)
        message_text: The text content of the message (exact match)
        forward_date: The date when the message was forwarded
        admin_chat_ids: List of chat IDs where the admin has permissions
        search_days_back: Number of days to search back from forward_date

    Returns:
        Dict with 'message_id' and 'chat_id' if found, None otherwise.
        Returns the most recent match within the search window.
    """
    if not admin_chat_ids:
        logger.debug("No admin chat IDs provided, skipping lookup")
        return None

    start_time = forward_date - timedelta(days=search_days_back)

    # Build the SQL query with string formatting (client doesn't support parameterized queries)
    chat_ids_str = ", ".join(f"'{chat_id}'" for chat_id in admin_chat_ids)

    # Use a more robust text matching approach - look for key distinctive phrases
    # Extract the first distinctive sentence that should be unique enough
    text_sample = message_text.split("\n\n")[0][:150].replace("'", "''")

    # Build user_id condition only if provided
    user_id_condition = ""
    if user_id is not None:
        user_id_condition = (
            f"AND (attributes->'update'->'message'->'from'->>'id')::bigint = {user_id}"
        )

    sql = f"""
    SELECT
        (attributes->'update'->'message'->>'message_id')::bigint as message_id,
        (attributes->'update'->'message'->'chat'->>'id')::bigint as chat_id,
        start_timestamp
    FROM records
    WHERE
        attributes->'update' IS NOT NULL
        AND attributes->'update'->'message' IS NOT NULL
        {user_id_condition}
        AND (
            position('{text_sample}' in attributes->'update'->'message'->>'text') > 0
            OR position('{text_sample}' in attributes->'update'->'message'->>'caption') > 0
        )
        AND (attributes->'update'->'message'->'chat'->>'id')::bigint IN ({chat_ids_str})
        AND start_timestamp >= '{start_time.isoformat()}'
    ORDER BY start_timestamp DESC
    LIMIT 1
    """

    try:
        client = _get_client()

        # Run the blocking query in a thread pool using query_json_rows for row-oriented results
        results = await asyncio.to_thread(
            client.query_json_rows,
            sql=sql,
            min_timestamp=start_time,
            limit=1,
        )

        if results and results.get("rows") and len(results["rows"]) > 0:
            row = results["rows"][0]
            message_id = int(row["message_id"])
            chat_id = int(row["chat_id"])
            logger.info(
                f"Found original message: message_id={message_id}, chat_id={chat_id}",
                extra={"logfire_lookup": "success"},
            )
            return {"message_id": message_id, "chat_id": chat_id}
        else:
            logger.info(
                "No matching message found in Logfire",
                extra={
                    "logfire_lookup": "miss",
                    "candidate_chats": len(admin_chat_ids),
                },
            )
            return None

    except Exception as e:
        logger.warning(
            f"Failed to query Logfire for original message: {e}",
            extra={"logfire_lookup": "error", "error": str(e)},
        )
        return None


async def get_weekly_stats(chat_ids: Sequence[int]) -> Dict[int, Dict[str, int]]:
    """
    Query Logfire for weekly statistics (last 7 days) for the given chat IDs.

    Args:
        chat_ids: List of chat IDs to get stats for

    Returns:
        Dict mapping chat_id to a dict with 'processed' and 'spam' counts.
    """
    if not chat_ids:
        return {}

    start_time = datetime.now() - timedelta(days=7)
    chat_ids_str = ", ".join(f"'{chat_id}'" for chat_id in chat_ids)

    # Tags indicating different outcomes
    spam_tags = {"message_spam_deleted"}
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

    # Default structure
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
        # Return empty stats (zeros) on failure
        return stats
