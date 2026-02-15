import asyncio
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Dict, Optional, Sequence

try:
    from logfire.query_client import LogfireQueryClient
except ImportError:
    raise ImportError(
        "logfire package is required for message lookup. Install with: pip install logfire"
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
    """
    Build SQL condition for user ID filtering.

    Args:
        user_id: User ID to filter by, or None to skip filtering

    Returns:
        SQL condition string for user ID filtering
    """
    if user_id is not None:
        return f"""
        AND (
            COALESCE(
                (attributes->'update'->'message'->'from'->>'id')::bigint,
                (attributes->'update'->'edited_message'->'from'->>'id')::bigint
            ) = {user_id}
        )
        """
    return ""


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

        if results and results.get("rows") and len(results["rows"]) > 0:
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

    sql = f"""
    SELECT
        attributes->'function_args'->>'stories_context' as stories_context,
        attributes->'function_args'->>'reply_context' as reply_context,
        attributes->'function_args'->>'account_age_context' as account_age_context,
        start_timestamp
    FROM records
    WHERE
        attributes->'function_name' = '"is_spam"'
        AND (
            attributes->'update'->'message'->>'message_id' = '{message_id}'
            OR attributes->'update'->'edited_message'->>'message_id' = '{message_id}'
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

    try:
        client = _get_client()

        # Run the blocking query in a thread pool
        results = await asyncio.to_thread(
            client.query_json_rows,
            sql=sql,
            min_timestamp=start_time,
            limit=1,
        )

        if results and results.get("rows") and len(results["rows"]) > 0:
            row = results["rows"][0]

            # Extract context fields, handling potential None values
            stories_context = row.get("stories_context")
            reply_context = row.get("reply_context")
            account_age_context = row.get("account_age_context")

            # Convert "null" strings to None (JSON null becomes "null" string in some cases)
            if stories_context == "null":
                stories_context = None
            if reply_context == "null":
                reply_context = None
            if account_age_context == "null":
                account_age_context = None

            logger.info(
                f"Found spam classification context: stories={bool(stories_context)}, reply={bool(reply_context)}, age={bool(account_age_context)}",
                extra={"logfire_context_lookup": "success"},
            )
            return {
                "stories_context": stories_context,
                "reply_context": reply_context,
                "account_age_context": account_age_context,
            }
        else:
            logger.info(
                "No spam classification context found in Logfire",
                extra={
                    "logfire_context_lookup": "miss",
                    "message_id": message_id,
                    "chat_id": chat_id,
                },
            )
            return None

    except Exception as e:
        logger.warning(
            f"Failed to query Logfire for spam classification context: {e}",
            extra={"logfire_context_lookup": "error", "error": str(e)},
        )
        return None
