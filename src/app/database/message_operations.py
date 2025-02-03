import logging
from datetime import datetime, timedelta
from typing import List

from .postgres_connection import get_pool

logger = logging.getLogger(__name__)

# Constants
MESSAGE_HISTORY_SIZE = 30  # Number of messages to keep in history
MESSAGE_TTL = 60 * 60 * 24  # 24 hours in seconds


async def save_message(admin_id: int, role: str, content: str) -> None:
    """Save a message to the admin's conversation history"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Insert new message
            await conn.execute(
                """
                INSERT INTO message_history (admin_id, role, content, created_at)
                VALUES ($1, $2, $3, NOW())
            """,
                admin_id,
                role,
                content,
            )

            # Get count of messages for this admin
            count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM message_history
                WHERE admin_id = $1
            """,
                admin_id,
            )

            # Remove oldest messages if exceeding limit
            if count > MESSAGE_HISTORY_SIZE:
                await conn.execute(
                    """
                    DELETE FROM message_history
                    WHERE id IN (
                        SELECT id FROM message_history
                        WHERE admin_id = $1
                        ORDER BY created_at ASC
                        LIMIT $2
                    )
                """,
                    admin_id,
                    count - MESSAGE_HISTORY_SIZE,
                )

            # Remove messages older than TTL
            expire_time = datetime.now() - timedelta(seconds=MESSAGE_TTL)
            await conn.execute(
                """
                DELETE FROM message_history
                WHERE admin_id = $1 AND created_at < $2
            """,
                admin_id,
                expire_time,
            )


async def get_message_history(admin_id: int) -> List[dict]:
    """Retrieve admin's conversation history"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT role, content
            FROM message_history
            WHERE admin_id = $1
            ORDER BY created_at ASC
        """,
            admin_id,
        )

        return [{"role": row["role"], "content": row["content"]} for row in rows]


async def clear_message_history(admin_id: int) -> None:
    """Clear admin's conversation history"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            DELETE FROM message_history WHERE admin_id = $1
        """,
            admin_id,
        )
