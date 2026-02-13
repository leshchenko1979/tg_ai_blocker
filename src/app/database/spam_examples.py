import logging
from typing import Any, Dict, List, Optional

import logfire

from ..common.utils import clean_alert_text
from .postgres_connection import get_pool

logger = logging.getLogger(__name__)

PENDING_SCORE = -100


@logfire.no_auto_trace
@logfire.instrument(extract_args=True)
async def insert_pending_spam_example(
    chat_id: int,
    message_id: int,
    effective_user_id: int,
    *,
    text: str = "[MEDIA_MESSAGE]",
    name: Optional[str] = None,
    bio: Optional[str] = None,
    linked_channel_fragment: Optional[str] = None,
    stories_context: Optional[str] = None,
    reply_context: Optional[str] = None,
    account_age_context: Optional[str] = None,
) -> int:
    """
    Insert a pending spam example. Run TTL cleanup, return new row id.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # TTL cleanup: delete stale pending rows (use '1 day' for SQLite compat in tests)
            await conn.execute(
                """
                DELETE FROM spam_examples
                WHERE confirmed = false
                AND created_at < NOW() - INTERVAL '1 day'
                """
            )

            row = await conn.fetchrow(
                """
                INSERT INTO spam_examples (
                    text, name, bio, score,
                    linked_channel_fragment, stories_context, reply_context, account_age_context,
                    confirmed, chat_id, message_id, effective_user_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, false, $9, $10, $11)
                RETURNING id
                """,
                text,
                name,
                bio,
                PENDING_SCORE,
                linked_channel_fragment,
                stories_context,
                reply_context,
                account_age_context,
                chat_id,
                message_id,
                effective_user_id,
            )
            return row["id"]


@logfire.no_auto_trace
@logfire.instrument(extract_args=True)
async def confirm_pending_spam_example(
    pending_id: int, admin_id: int
) -> Optional[Dict[str, Any]]:
    """
    Confirm a pending spam example. Returns chat_id, message_id, effective_user_id
    if row found and was pending; None otherwise.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE spam_examples
            SET confirmed = true, admin_id = $1
            WHERE id = $2 AND confirmed = false
            RETURNING chat_id, message_id, effective_user_id
            """,
            admin_id,
            pending_id,
        )
        if not row or row["chat_id"] is None:
            return None
        return {
            "chat_id": row["chat_id"],
            "message_id": row["message_id"],
            "effective_user_id": row["effective_user_id"],
        }


async def get_spam_examples(
    admin_ids: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    """Get spam examples from PostgreSQL, including user-specific examples if admin_ids is provided"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if admin_ids:
            # Get both common and user-specific examples for multiple admins
            rows = await conn.fetch(
                """
                SELECT text, name, bio, score, linked_channel_fragment, stories_context, reply_context, account_age_context
                FROM spam_examples
                WHERE (admin_id IS NULL OR admin_id = ANY($1)) AND (confirmed IS NOT DISTINCT FROM true)
                ORDER BY created_at DESC
            """,
                admin_ids,
            )
        else:
            # Get only common examples
            rows = await conn.fetch(
                """
                SELECT text, name, bio, score, linked_channel_fragment, stories_context, reply_context, account_age_context
                FROM spam_examples
                WHERE admin_id IS NULL AND (confirmed IS NOT DISTINCT FROM true)
                ORDER BY created_at DESC
            """
            )

        return [
            {
                "text": row["text"],
                "name": row["name"],
                "bio": row["bio"],
                "score": row["score"],
                "linked_channel_fragment": row["linked_channel_fragment"],
                "stories_context": row["stories_context"],
                "reply_context": row["reply_context"],
                "account_age_context": row["account_age_context"],
            }
            for row in rows
        ]


@logfire.no_auto_trace
@logfire.instrument(extract_args=True)
async def add_spam_example(
    text: str,
    score: int,
    name: Optional[str] = None,
    bio: Optional[str] = None,
    admin_id: Optional[int] = None,
    linked_channel_fragment: Optional[str] = None,
    stories_context: Optional[str] = None,
    reply_context: Optional[str] = None,
    account_age_context: Optional[str] = None,
) -> bool:
    """Add a new spam example to PostgreSQL"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                # Очистка текста от служебных обёрток
                cleaned_text = clean_alert_text(text)
                # Remove existing example with same text and name if exists (confirmed only)
                await conn.execute(
                    """
                    DELETE FROM spam_examples
                    WHERE text = $1 AND (name = $2 OR (name IS NULL AND $2 IS NULL))
                    AND (admin_id = $3 OR (admin_id IS NULL AND $3 IS NULL))
                    AND (confirmed IS NOT DISTINCT FROM true)
                """,
                    cleaned_text,
                    name,
                    admin_id,
                )

                # Add new example
                await conn.execute(
                    """
                    INSERT INTO spam_examples (
                        text,
                        name,
                        bio,
                        score,
                        admin_id,
                        linked_channel_fragment,
                        stories_context,
                        reply_context,
                        account_age_context,
                        created_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
                """,
                    cleaned_text,
                    name,
                    bio,
                    score,
                    admin_id,
                    linked_channel_fragment,
                    stories_context,
                    reply_context,
                    account_age_context,
                )
                return True
            except Exception as e:
                logger.error(f"Error adding spam example: {e}")
                return False


async def remove_spam_example(text: str) -> bool:
    """Remove a spam example from PostgreSQL by its text (confirmed only)"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            result = await conn.execute(
                """
                DELETE FROM spam_examples
                WHERE text = $1 AND admin_id IS NULL AND (confirmed IS NOT DISTINCT FROM true)
            """,
                text,
            )
            return result != "DELETE 0"
        except Exception as e:
            logger.error(f"Error removing spam example: {e}")
            return False
