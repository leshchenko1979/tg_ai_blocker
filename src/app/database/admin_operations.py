import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..common.mp import mp
from .constants import INITIAL_CREDITS
from .models import Administrator
from .postgres_connection import get_pool

logger = logging.getLogger(__name__)


async def save_admin(admin: Administrator) -> None:
    """Save administrator to PostgreSQL"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO administrators (
                admin_id, username, credits, delete_spam, created_at, last_active
            ) VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (admin_id) DO UPDATE SET
                username = $2,
                credits = $3,
                delete_spam = $4,
                last_active = $6
        """,
            admin.admin_id,
            admin.username,
            admin.credits,
            admin.delete_spam,
            admin.created_at,
            admin.last_updated,
        )


async def get_admin(admin_id: int) -> Optional[Administrator]:
    """Retrieve administrator information from PostgreSQL"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM administrators WHERE admin_id = $1
        """,
            admin_id,
        )

        if not row:
            return None

        return Administrator(
            admin_id=row["admin_id"],
            username=row["username"],
            credits=row["credits"],
            is_active=True,  # Always true if record exists
            delete_spam=row["delete_spam"],
            created_at=row["created_at"],
            last_updated=row["last_active"],
        )


async def get_admin_credits(admin_id: int) -> int:
    """Retrieve administrator credits"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        credits = await conn.fetchval(
            """
            SELECT credits FROM administrators WHERE admin_id = $1
        """,
            admin_id,
        )
        return credits if credits is not None else INITIAL_CREDITS


async def initialize_new_admin(admin_id: int) -> bool:
    """Initialize a new administrator with initial credits"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Check if user exists
            exists = await conn.fetchval(
                """
                SELECT EXISTS(SELECT 1 FROM administrators WHERE admin_id = $1)
            """,
                admin_id,
            )

            if exists:
                return False

            # Create new user
            await conn.execute(
                """
                INSERT INTO administrators (
                    admin_id, credits, delete_spam, created_at, last_active
                ) VALUES ($1, $2, true, NOW(), NOW())
            """,
                admin_id,
                INITIAL_CREDITS,
            )

            # Record initial credit transaction
            await conn.execute(
                """
                INSERT INTO transactions (admin_id, amount, type, description)
                VALUES ($1, $2, 'initial', 'Initial credits')
            """,
                admin_id,
                INITIAL_CREDITS,
            )

            return True


async def toggle_spam_deletion(admin_id: int) -> bool | None:
    """Toggle spam deletion setting for administrator. Returns new state"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Get current state
            current_state = await conn.fetchval(
                """
                SELECT delete_spam FROM administrators WHERE admin_id = $1
            """,
                admin_id,
            )

            if current_state is None:
                return None

            # Toggle state
            new_state = not current_state

            # Update state
            await conn.execute(
                """
                UPDATE administrators
                SET delete_spam = $1, last_active = NOW()
                WHERE admin_id = $2
            """,
                new_state,
                admin_id,
            )

            return new_state


async def get_spam_deletion_state(admin_id: int) -> bool:
    """Get current spam deletion state for administrator"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        state = await conn.fetchval(
            """
            SELECT delete_spam FROM administrators WHERE admin_id = $1
        """,
            admin_id,
        )
        return (
            bool(state) if state is not None else True
        )  # Default to True if not found


async def get_spent_credits_last_week(admin_id: int) -> int:
    """Get total spent credits for the last 7 days"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            SELECT COALESCE(SUM(ABS(amount)), 0)
            FROM transactions
            WHERE admin_id = $1
            AND amount < 0
            AND created_at >= NOW() - INTERVAL '7 days'
        """,
            admin_id,
        )


async def get_all_admins() -> List[Administrator]:
    """Get list of all administrators"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM administrators
            ORDER BY created_at DESC
            """
        )

        return [
            Administrator(
                admin_id=row["admin_id"],
                username=row["username"],
                credits=row["credits"],
                is_active=True,  # Always true if record exists
                delete_spam=row["delete_spam"],
                created_at=row["created_at"],
                last_updated=row["last_active"],
            )
            for row in rows
        ]


async def remove_admin(admin_id: int) -> None:
    """Remove administrator from database"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Remove from administrators (all related records will be deleted automatically)
            await conn.execute(
                """
                DELETE FROM administrators
                WHERE admin_id = $1
                """,
                admin_id,
            )

            # Track removal in Mixpanel
            mp.track(
                admin_id,
                "admin_removed",
                {
                    "reason": "bot_blocked",
                    "timestamp": datetime.now().isoformat(),
                },
            )


async def get_admin_stats(admin_id: int) -> Dict[str, Any]:
    """
    Get comprehensive statistics for an administrator.
    Includes global stats and per-group stats with Logfire metrics.
    """
    from ..common.logfire_lookup import get_weekly_stats
    from .group_operations import get_admin_groups

    # Get groups managed by admin
    groups = await get_admin_groups(admin_id)

    if not groups:
        return {
            "global": {
                "processed": 0,
                "spam": 0,
                "approved": 0,
            },
            "groups": [],
        }

    group_ids = [g["id"] for g in groups]

    # Fetch Logfire weekly stats
    weekly_stats = await get_weekly_stats(group_ids)

    # Fetch approved members count for each group
    pool = await get_pool()
    async with pool.acquire() as conn:
        approved_counts = await conn.fetch(
            """
            SELECT group_id, COUNT(*) as count
            FROM approved_members
            WHERE group_id = ANY($1::bigint[])
            GROUP BY group_id
            """,
            group_ids,
        )

        # Fetch spam examples count for this admin
        spam_examples_count = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM spam_examples
            WHERE admin_id = $1
            """,
            admin_id,
        )

    approved_map = {row["group_id"]: row["count"] for row in approved_counts}

    # Aggregate data
    global_processed = 0
    global_spam = 0
    global_approved = sum(approved_map.values())

    enriched_groups = []
    for group in groups:
        gid = group["id"]
        w_stats = weekly_stats.get(gid, {"processed": 0, "spam": 0})

        global_processed += w_stats["processed"]
        global_spam += w_stats["spam"]

        enriched_groups.append(
            {
                "title": group["title"],
                "is_moderation_enabled": group["is_moderation_enabled"],
                "approved_users_count": approved_map.get(gid, 0),
                "stats": w_stats,
            }
        )

    return {
        "global": {
            "processed": global_processed,
            "spam": global_spam,
            "approved": global_approved,
            "spam_examples": spam_examples_count or 0,
        },
        "groups": enriched_groups,
    }
