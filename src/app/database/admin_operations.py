from typing import Any, Dict, List, Optional

from .constants import INITIAL_CREDITS
from .models import Administrator
from .postgres_connection import get_pool


async def save_admin(admin: Administrator) -> None:
    """Save administrator to PostgreSQL"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO administrators (
                admin_id, username, credits, delete_spam, is_active, language_code, created_at, last_active
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (admin_id) DO UPDATE SET
                username = EXCLUDED.username,
                credits = EXCLUDED.credits,
                delete_spam = EXCLUDED.delete_spam,
                is_active = EXCLUDED.is_active,
                language_code = EXCLUDED.language_code,
                last_active = EXCLUDED.last_active
        """,
            admin.admin_id,
            admin.username,
            admin.credits,
            admin.delete_spam,
            admin.is_active,
            admin.language_code,
            admin.created_at,
            admin.last_updated,
        )


async def update_admin_language(admin_id: int, language_code: str) -> None:
    """Update administrator's preferred language. Supports 'ru' and 'en'."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE administrators
            SET language_code = $1, last_active = NOW()
            WHERE admin_id = $2
            """,
            language_code,
            admin_id,
        )


async def update_admin_username_if_needed(admin_id: int, username: str | None) -> None:
    """Update administrator's username if it changed. No-op if username is None or unchanged."""
    if not username:
        return
    admin = await get_admin(admin_id)
    if admin and (admin.username is None or admin.username != username):
        admin.username = username
        await save_admin(admin)


async def record_successful_payment(admin_id: int, stars_amount: int) -> None:
    """Record a successful Stars payment: add credits, record transaction, enable moderation."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "CALL process_successful_payment($1, $2)",
            admin_id,
            stars_amount,
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

        is_active_column = row["is_active"] if "is_active" in row.keys() else True
        language_code = row["language_code"] if "language_code" in row.keys() else None

        return Administrator(
            admin_id=row["admin_id"],
            username=row["username"],
            credits=row["credits"],
            is_active=is_active_column,
            delete_spam=row["delete_spam"],
            language_code=language_code,
            created_at=row["created_at"],
            last_updated=row["last_active"],
        )


async def get_admins_map(admin_ids: list[int]) -> dict[int, Administrator]:
    """Retrieve multiple administrators information from PostgreSQL in a single query"""
    if not admin_ids:
        return {}

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM administrators WHERE admin_id = ANY($1::bigint[])
        """,
            admin_ids,
        )

        return {
            row["admin_id"]: Administrator(
                admin_id=row["admin_id"],
                username=row["username"],
                credits=row["credits"],
                is_active=row["is_active"] if "is_active" in row.keys() else True,
                delete_spam=row["delete_spam"],
                language_code=(
                    row["language_code"] if "language_code" in row.keys() else None
                ),
                created_at=row["created_at"],
                last_updated=row["last_active"],
            )
            for row in rows
        }


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


async def initialize_new_admin(
    admin_id: int,
    *,
    language_code: str | None = None,
) -> bool:
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
                    admin_id, credits, delete_spam, is_active, language_code, created_at, last_active
                ) VALUES ($1, $2, false, TRUE, $3, NOW(), NOW())
            """,
                admin_id,
                INITIAL_CREDITS,
                language_code,
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
            WHERE is_active = TRUE
            ORDER BY created_at DESC
            """
        )

    return [
        Administrator(
            admin_id=row["admin_id"],
            username=row["username"],
            credits=row["credits"],
            is_active=row.get("is_active", True),
            delete_spam=row["delete_spam"],
            language_code=(
                row["language_code"] if "language_code" in row.keys() else None
            ),
            created_at=row["created_at"],
            last_updated=row["last_active"],
        )
        for row in rows
    ]


async def deactivate_admin(admin_id: int) -> bool:
    """Mark the administrator as inactive after a failure"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE administrators
            SET is_active = FALSE, last_active = NOW()
            WHERE admin_id = $1 AND is_active = TRUE
            RETURNING admin_id
            """,
            admin_id,
        )

    return row is not None


async def set_credits_depleted_at(admin_id: int) -> None:
    """Set credits_depleted_at = NOW() when admin credits hit 0. No-op if already set."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE administrators
            SET credits_depleted_at = NOW(), last_active = NOW()
            WHERE admin_id = $1 AND credits = 0 AND credits_depleted_at IS NULL
            """,
            admin_id,
        )


async def mark_low_balance_warned(admin_id: int) -> None:
    """Record that the week-ahead low balance warning was sent."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE administrators
            SET low_balance_warned_at = NOW(), last_active = NOW()
            WHERE admin_id = $1
            """,
            admin_id,
        )


async def get_admins_for_low_balance_warnings(
    threshold: int,
) -> List[Dict[str, Any]]:
    """
    Get active admins who need week-ahead warning: credits < min(threshold, spent_last_week)
    and not yet warned.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT a.admin_id, a.credits,
                COALESCE(
                    (SELECT SUM(ABS(amount))::int
                     FROM transactions t
                     WHERE t.admin_id = a.admin_id AND t.amount < 0
                       AND t.created_at >= NOW() - INTERVAL '7 days'),
                    0
                ) as spent_last_week
            FROM administrators a
            WHERE a.is_active = TRUE
              AND a.low_balance_warned_at IS NULL
              AND a.credits > 0
            """,
        )

    result = []
    for row in rows:
        spent = row["spent_last_week"] or 0
        limit = min(threshold, spent) if spent > 0 else threshold
        if row["credits"] < limit:
            result.append(
                {
                    "admin_id": row["admin_id"],
                    "credits": row["credits"],
                    "spent_last_week": spent,
                }
            )
    return result


async def clear_depletion_flags(admin_id: int) -> None:
    """Clear credits_depleted_at after day-7 processing so admin is not re-processed daily."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE administrators
            SET credits_depleted_at = NULL, last_active = NOW()
            WHERE admin_id = $1
            """,
            admin_id,
        )


async def get_admins_for_depletion_timeline() -> List[Dict[str, Any]]:
    """Get active admins with credits_depleted_at set for timeline checks."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT admin_id, credits_depleted_at
            FROM administrators
            WHERE is_active = TRUE AND credits_depleted_at IS NOT NULL
            """,
        )
    return [
        {"admin_id": row["admin_id"], "credits_depleted_at": row["credits_depleted_at"]}
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
        # Fetch spam examples count for this admin even when they have no groups
        pool = await get_pool()
        async with pool.acquire() as conn:
            spam_examples_count = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM spam_examples
                WHERE admin_id = $1 AND (confirmed IS NOT DISTINCT FROM true)
                """,
                admin_id,
            )
        return {
            "global": {
                "processed": 0,
                "spam": 0,
                "approved": 0,
                "spam_examples": spam_examples_count or 0,
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
            WHERE admin_id = $1 AND (confirmed IS NOT DISTINCT FROM true)
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
