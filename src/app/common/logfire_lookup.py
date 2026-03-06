import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Sequence

try:
    from logfire.query_client import LogfireQueryClient
except ImportError:
    raise ImportError(
        "logfire package is required for message lookup. Install with: pip install logfire"
    )

from ..types import ContextResult, UserAccountInfo

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


def _build_text_matching_condition(message_text: str) -> str:
    """
    Build a robust SQL text matching condition that handles hidden characters.

    This function implements a multi-strategy approach:
    1. First, extract distinctive words from the message text
    2. Create a LIKE pattern that joins words with wildcards to bypass hidden characters
    3. Fall back to substring matching if no distinctive words are found

    The LIKE pattern approach is crucial because it allows matching text that contains
    zero-width spaces, word joiners, or other invisible Unicode characters that might
    be inserted by spam bots to evade detection.

    Args:
        message_text: The text content to create matching conditions for

    Returns:
        SQL condition string for text matching in WHERE clause
    """
    # Extract distinctive words from the first paragraph (limited to 150 chars)
    # This focuses on the most relevant content while avoiding noise from long messages
    first_paragraph = message_text.split("\n\n")[0][:150]
    distinctive_words = re.findall(r"\w+", first_paragraph)

    if distinctive_words:
        # Create a robust LIKE pattern by joining first 10 words with wildcards
        # This allows matching even if hidden characters are inserted between words
        # Example: ["hello", "world", "spam"] -> "%hello%world%spam%"
        word_pattern = "%".join(distinctive_words[:10])

        # Escape single quotes for SQL safety
        escaped_pattern = word_pattern.replace("'", "''")

        return f"""
        (
            attributes->'update'->'message'->>'text' LIKE '%{escaped_pattern}%'
            OR attributes->'update'->'message'->>'caption' LIKE '%{escaped_pattern}%'
            OR attributes->'update'->'edited_message'->>'text' LIKE '%{escaped_pattern}%'
            OR attributes->'update'->'edited_message'->>'caption' LIKE '%{escaped_pattern}%'
        )
        """

    else:
        # Fallback: Use substring matching for messages with no alphanumeric content
        # This handles cases like emoji-only messages or messages with special characters
        text_sample = message_text[:100].replace("'", "''")

        return f"""
        (
            position('{text_sample}' in attributes->'update'->'message'->>'text') > 0
            OR position('{text_sample}' in attributes->'update'->'message'->>'caption') > 0
            OR position('{text_sample}' in attributes->'update'->'edited_message'->>'text') > 0
            OR position('{text_sample}' in attributes->'update'->'edited_message'->>'caption') > 0
        )
        """


def _build_user_id_condition(user_id: Optional[int]) -> str:
    """Build SQL condition for user ID filtering, or empty string if user_id is None."""
    if user_id is None:
        return ""
    return f"""
        AND (
            COALESCE(
                (attributes->'update'->'message'->'from'->>'id')::bigint,
                (attributes->'update'->'edited_message'->'from'->>'id')::bigint
            ) = {user_id}
        )
        """


def _has_rows(result: Any) -> bool:
    """Return True if result contains at least one row."""
    return bool(result and result.get("rows"))


def _parse_attributes(attrs_raw: Any) -> Optional[Dict]:
    """Parse attributes from Logfire record; return dict or None if invalid."""
    if not attrs_raw:
        return None
    if isinstance(attrs_raw, str):
        try:
            return json.loads(attrs_raw)
        except json.JSONDecodeError:
            return None
    return attrs_raw if isinstance(attrs_raw, dict) else None


async def find_original_message(
    user_id: Optional[int],
    message_text: str,
    forward_date: datetime,
    admin_chat_ids: Sequence[int],
    search_days_back: int = 3,
) -> Optional[Dict[str, int | None]]:
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

    # Build text matching condition using robust approach that handles hidden characters
    text_condition = _build_text_matching_condition(message_text)

    # Build user ID condition if provided
    user_id_condition = _build_user_id_condition(user_id)

    sql = f"""
    SELECT
        COALESCE(
            (attributes->'update'->'message'->>'message_id')::bigint,
            (attributes->'update'->'edited_message'->>'message_id')::bigint
        ) as message_id,
        COALESCE(
            (attributes->'update'->'message'->'chat'->>'id')::bigint,
            (attributes->'update'->'edited_message'->'chat'->>'id')::bigint
        ) as chat_id,
        COALESCE(
            (attributes->'update'->'message'->'from'->>'id')::bigint,
            (attributes->'update'->'edited_message'->'from'->>'id')::bigint
        ) as user_id,
        start_timestamp
    FROM records
    WHERE
        attributes->'update' IS NOT NULL
        AND (
            attributes->'update'->'message' IS NOT NULL
            OR attributes->'update'->'edited_message' IS NOT NULL
        )
        {user_id_condition}
        AND {text_condition}
        AND COALESCE(
            (attributes->'update'->'message'->'chat'->>'id')::bigint,
            (attributes->'update'->'edited_message'->'chat'->>'id')::bigint
        ) IN ({chat_ids_str})
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

        if _has_rows(results):
            row = results["rows"][0]
            message_id = int(row["message_id"])
            chat_id = int(row["chat_id"])
            user_id_result = int(row["user_id"]) if row.get("user_id") else None
            logger.info(
                f"Found original message: message_id={message_id}, chat_id={chat_id}, user_id={user_id_result}",
                extra={"logfire_lookup": "success"},
            )
            return {
                "message_id": message_id,
                "chat_id": chat_id,
                "user_id": user_id_result,
            }
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


async def find_spam_classification_context(
    message_id: int,
    chat_id: int,
    user_id: Optional[int],
    forward_date: datetime,
    search_days_back: int = 3,
) -> Optional[Dict[str, Optional[str]]]:
    """
    Query Logfire to find the spam classification context for a message.

    Uses a two-step approach: (1) find trace_id from a record with the update,
    (2) find the is_spam span in that trace and extract context from attributes.context.

    Args:
        message_id: The ID of the message that was classified
        chat_id: The chat ID where the message was sent
        user_id: The user ID who sent the message (optional)
        forward_date: The date when the message was forwarded
        search_days_back: Number of days to search back from forward_date

    Returns:
        Dict with context fields ('stories_context', 'reply_context', 'account_age_context') if found, None otherwise.
        Returns context from the most recent spam classification within the search window.
    """
    start_time = forward_date - timedelta(days=search_days_back)

    # Build user ID condition if provided
    user_id_condition = _build_user_id_condition(user_id)

    try:
        client = _get_client()

        # Step 1: Find trace_id from a record that has the update (message metadata)
        step1_sql = f"""
        SELECT trace_id
        FROM records
        WHERE
            attributes->'update' IS NOT NULL
            AND (
                attributes->'update'->'message' IS NOT NULL
                OR attributes->'update'->'edited_message' IS NOT NULL
            )
            AND (
                (attributes->'update'->'message'->>'message_id') = '{message_id}'
                OR (attributes->'update'->'edited_message'->>'message_id') = '{message_id}'
            )
            AND COALESCE(
                (attributes->'update'->'message'->'chat'->>'id')::bigint,
                (attributes->'update'->'edited_message'->'chat'->>'id')::bigint
            ) = {chat_id}
            {user_id_condition}
            AND start_timestamp >= '{start_time.isoformat()}'
        ORDER BY start_timestamp DESC
        LIMIT 1
        """

        step1_results = await asyncio.to_thread(
            client.query_json_rows,
            sql=step1_sql,
            min_timestamp=start_time,
            limit=1,
        )

        if not _has_rows(step1_results):
            logger.info(
                "No spam classification context found in Logfire",
                extra={
                    "logfire_context_lookup": "miss",
                    "message_id": message_id,
                    "chat_id": chat_id,
                },
            )
            return None

        trace_id = step1_results["rows"][0].get("trace_id")
        if not trace_id:
            logger.info(
                "Trace has no trace_id",
                extra={
                    "logfire_context_lookup": "miss",
                    "message_id": message_id,
                    "chat_id": chat_id,
                },
            )
            return None

        # Step 2: Find is_spam span in that trace and extract context from attributes.context
        trace_id_escaped = trace_id.replace("'", "''")
        step2_sql = f"""
        SELECT attributes
        FROM records
        WHERE
            trace_id = '{trace_id_escaped}'
            AND span_name LIKE '%spam_classifier.is_spam%'
        ORDER BY start_timestamp ASC
        LIMIT 1
        """

        step2_results = await asyncio.to_thread(
            client.query_json_rows,
            sql=step2_sql,
            min_timestamp=start_time,
            limit=1,
        )

        if not _has_rows(step2_results):
            logger.info(
                "No is_spam span found in trace",
                extra={
                    "logfire_context_lookup": "miss",
                    "message_id": message_id,
                    "chat_id": chat_id,
                    "trace_id": trace_id,
                },
            )
            return None

        attrs = _parse_attributes(step2_results["rows"][0].get("attributes"))
        if attrs is None:
            logger.info(
                "is_spam span attributes invalid",
                extra={
                    "logfire_context_lookup": "miss",
                    "message_id": message_id,
                    "chat_id": chat_id,
                },
            )
            return None

        context = attrs.get("context")
        if not context or not isinstance(context, dict):
            logger.info(
                "is_spam span has no context",
                extra={
                    "logfire_context_lookup": "miss",
                    "message_id": message_id,
                    "chat_id": chat_id,
                },
            )
            return None

        # Extract reply (direct string; empty or "null" becomes None)
        reply_raw = context.get("reply")
        reply_context = (
            reply_raw
            if isinstance(reply_raw, str) and reply_raw != "null" and reply_raw.strip()
            else None
        )

        # Extract stories (ContextResult-like: status, content)
        stories_obj = context.get("stories")
        stories_context = ContextResult.fragment_from_logfire_dict(stories_obj)

        # Extract account_age (ContextResult-like; content is dict with profile_photo_date)
        account_age_obj = context.get("account_age")
        account_age_context = None
        if account_age_obj and isinstance(account_age_obj, dict):
            status = account_age_obj.get("status")
            content = account_age_obj.get("content")
            if status == "found" and content:
                account_age_context = UserAccountInfo.fragment_from_logfire_dict(
                    content
                )
            elif status == "empty":
                account_age_context = "[EMPTY]"

        result = {
            "stories_context": stories_context,
            "reply_context": reply_context,
            "account_age_context": account_age_context,
        }

        logger.info(
            f"Found spam classification context: stories={bool(stories_context)}, reply={bool(reply_context)}, age={bool(account_age_context)}",
            extra={"logfire_context_lookup": "success"},
        )
        return result

    except Exception as e:
        logger.warning(
            f"Failed to query Logfire for spam classification context: {e}",
            extra={"logfire_context_lookup": "error", "error": str(e)},
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

        if _has_rows(results):
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
