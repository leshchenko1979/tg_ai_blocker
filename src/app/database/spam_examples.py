import logging
from typing import Any, Dict, List, Optional

from ..common.utils import clean_alert_text
from .postgres_connection import get_pool

logger = logging.getLogger(__name__)


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
                SELECT text, name, bio, score
                FROM spam_examples
                WHERE admin_id IS NULL OR admin_id = ANY($1)
                ORDER BY created_at DESC
            """,
                admin_ids,
            )
        else:
            # Get only common examples
            rows = await conn.fetch(
                """
                SELECT text, name, bio, score
                FROM spam_examples
                WHERE admin_id IS NULL
                ORDER BY created_at DESC
            """
            )

        return [
            {
                "text": row["text"],
                "name": row["name"],
                "bio": row["bio"],
                "score": row["score"],
            }
            for row in rows
        ]


async def add_spam_example(
    text: str,
    score: int,
    name: Optional[str] = None,
    bio: Optional[str] = None,
    admin_id: Optional[int] = None,
) -> bool:
    """Add a new spam example to PostgreSQL"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                # Очистка текста от служебных обёрток
                cleaned_text = clean_alert_text(text)
                # Remove existing example with same text and name if exists
                await conn.execute(
                    """
                    DELETE FROM spam_examples
                    WHERE text = $1 AND (name = $2 OR (name IS NULL AND $2 IS NULL))
                    AND (admin_id = $3 OR (admin_id IS NULL AND $3 IS NULL))
                """,
                    cleaned_text,
                    name,
                    admin_id,
                )

                # Add new example
                await conn.execute(
                    """
                    INSERT INTO spam_examples (text, name, bio, score, admin_id, created_at)
                    VALUES ($1, $2, $3, $4, $5, NOW())
                """,
                    cleaned_text,
                    name,
                    bio,
                    score,
                    admin_id,
                )
                return True
            except Exception as e:
                logger.error(f"Error adding spam example: {e}")
                return False


async def remove_spam_example(text: str) -> bool:
    """Remove a spam example from PostgreSQL by its text"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            result = await conn.execute(
                """
                DELETE FROM spam_examples
                WHERE text = $1 AND admin_id IS NULL
            """,
                text,
            )
            return result != "DELETE 0"
        except Exception as e:
            logger.error(f"Error removing spam example: {e}")
            return False
