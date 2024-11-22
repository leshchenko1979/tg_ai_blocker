import json
from typing import Any, Dict, List, Optional

from ..yandex_logging import get_yandex_logger, log_function_call
from .postgres_connection import get_pool

logger = get_yandex_logger(__name__)


@log_function_call(logger)
async def get_spam_examples(admin_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Get spam examples from PostgreSQL, including user-specific examples if admin_id is provided"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if admin_id is not None:
            # Get both common and user-specific examples
            rows = await conn.fetch(
                """
                SELECT text, name, bio, score
                FROM spam_examples
                WHERE admin_id IS NULL OR admin_id = $1
                ORDER BY created_at DESC
            """,
                admin_id,
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


@log_function_call(logger)
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
                # Remove existing example with same text and name if exists
                await conn.execute(
                    """
                    DELETE FROM spam_examples
                    WHERE text = $1 AND (name = $2 OR (name IS NULL AND $2 IS NULL))
                    AND (admin_id = $3 OR (admin_id IS NULL AND $3 IS NULL))
                """,
                    text,
                    name,
                    admin_id,
                )

                # Add new example
                await conn.execute(
                    """
                    INSERT INTO spam_examples (text, name, bio, score, admin_id, created_at)
                    VALUES ($1, $2, $3, $4, $5, NOW())
                """,
                    text,
                    name,
                    bio,
                    score,
                    admin_id,
                )
                return True
            except Exception as e:
                logger.error(f"Error adding spam example: {e}")
                return False


@log_function_call(logger)
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
