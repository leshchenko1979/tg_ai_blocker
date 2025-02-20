import logging
from typing import Dict, List, Optional

from ..common.bot import bot
from ..common.mp import mp
from . import admin_operations
from .constants import INITIAL_CREDITS
from .models import Administrator, Group
from .postgres_connection import get_pool

logger = logging.getLogger(__name__)


async def get_group(group_id: int) -> Optional[Group]:
    """Retrieve group information"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        group_data = await conn.fetchrow(
            """
            SELECT * FROM groups WHERE group_id = $1
        """,
            group_id,
        )

        if not group_data:
            return None

        admin_ids = [
            row["admin_id"]
            for row in await conn.fetch(
                """
            SELECT admin_id FROM group_administrators WHERE group_id = $1
        """,
                group_id,
            )
        ]

        member_ids = [
            row["member_id"]
            for row in await conn.fetch(
                """
            SELECT member_id FROM approved_members WHERE group_id = $1
        """,
                group_id,
            )
        ]

        return Group(
            group_id=group_id,
            admin_ids=admin_ids,
            moderation_enabled=group_data["moderation_enabled"],
            member_ids=member_ids,
            created_at=group_data["created_at"],
            last_updated=group_data["last_active"],
        )


async def set_group_moderation(group_id: int, enabled: bool) -> None:
    """Enable/disable moderation for a group"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO groups (group_id, moderation_enabled, last_active)
            VALUES ($1, $2, NOW())
            ON CONFLICT (group_id) DO UPDATE
            SET moderation_enabled = $2, last_active = NOW()
        """,
            group_id,
            enabled,
        )


async def is_moderation_enabled(group_id: int) -> bool:
    """Check if moderation is enabled for a group"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        enabled = await conn.fetchval(
            """
            SELECT moderation_enabled FROM groups WHERE group_id = $1
        """,
            group_id,
        )
        return bool(enabled)


async def get_paying_admins(group_id: int) -> List[int]:
    """Get list of admins with positive credits"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT a.admin_id
            FROM administrators a
            JOIN group_administrators ga ON a.admin_id = ga.admin_id
            WHERE ga.group_id = $1 AND a.credits > 0
        """,
            group_id,
        )
        return [row["admin_id"] for row in rows]


async def deduct_credits_from_admins(group_id: int, amount: int) -> int:
    """
    Deduct credits from the admin with the highest balance
    Returns:
        int: admin_id if credits were successfully deducted, 0 if deduction failed
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Find admin with highest balance
            admin_row = await conn.fetchrow(
                """
                SELECT a.admin_id, a.credits
                FROM administrators a
                JOIN group_administrators ga ON a.admin_id = ga.admin_id
                WHERE ga.group_id = $1
                ORDER BY a.credits DESC
                LIMIT 1
            """,
                group_id,
            )

            if not admin_row or admin_row["credits"] < amount:
                return 0

            # Deduct credits and record transaction
            await conn.execute(
                """
                UPDATE administrators
                SET credits = credits - $1, last_active = NOW()
                WHERE admin_id = $2
            """,
                amount,
                admin_row["admin_id"],
            )

            await conn.execute(
                """
                INSERT INTO transactions (admin_id, amount, type, description)
                VALUES ($1, $2, 'deduct', 'Group moderation credit deduction')
            """,
                admin_row["admin_id"],
                -amount,
            )

            return admin_row["admin_id"]


async def get_admin_groups(admin_id: int) -> List[Dict]:
    """Get list of groups where user is an admin"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT g.group_id, g.title, g.moderation_enabled
            FROM groups g
            JOIN group_administrators ga ON g.group_id = ga.group_id
            WHERE ga.admin_id = $1
        """,
            admin_id,
        )

        groups = []
        for row in rows:
            try:
                chat = await bot.get_chat(row["group_id"])
                groups.append(
                    {
                        "id": row["group_id"],
                        "title": chat.title,
                        "is_moderation_enabled": row["moderation_enabled"],
                    }
                )
            except Exception as e:
                logger.error(
                    f"Error getting chat {row['group_id']}: {e}", exc_info=True
                )
                continue

        # Update Mixpanel profile with current group count
        mp.people_set(admin_id, {"managed_groups_count": len(groups)})

        return groups


async def is_member_in_group(group_id: int, member_id: int) -> bool:
    """Check if member is in group"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1 FROM approved_members
                WHERE group_id = $1 AND member_id = $2
            )
        """,
            group_id,
            member_id,
        )
        return bool(exists)


async def add_member(group_id: int, member_id: int) -> None:
    """Add unique member to group"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO approved_members (group_id, member_id)
            VALUES ($1, $2)
            ON CONFLICT DO NOTHING
        """,
            group_id,
            member_id,
        )


async def remove_member_from_group(
    member_id: int, group_id: Optional[int] = None
) -> None:
    """Remove a member from a group or all groups"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if group_id is not None:
                # Remove from specific group
                await conn.execute(
                    """
                    DELETE FROM approved_members
                    WHERE group_id = $1 AND member_id = $2
                """,
                    group_id,
                    member_id,
                )

                await conn.execute(
                    """
                    UPDATE groups SET last_active = NOW()
                    WHERE group_id = $1
                """,
                    group_id,
                )
            else:
                # Remove from all groups
                groups = await conn.fetch(
                    """
                    SELECT DISTINCT group_id
                    FROM approved_members
                    WHERE member_id = $1
                """,
                    member_id,
                )

                await conn.execute(
                    """
                    DELETE FROM approved_members WHERE member_id = $1
                """,
                    member_id,
                )

                if groups:
                    await conn.execute(
                        """
                        UPDATE groups SET last_active = NOW()
                        WHERE group_id = ANY($1::bigint[])
                    """,
                        [g["group_id"] for g in groups],
                    )


async def update_group_admins(group_id: int, admin_ids: List[int]) -> None:
    """Update list of group administrators"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Ensure group exists
            await conn.execute(
                """
                INSERT INTO groups (group_id, moderation_enabled, created_at, last_active)
                VALUES ($1, TRUE, NOW(), NOW())
                ON CONFLICT (group_id) DO UPDATE
                SET last_active = NOW()
                """,
                group_id,
            )

            # Get current admins
            current_admins = [
                row["admin_id"]
                for row in await conn.fetch(
                    """
                    SELECT admin_id FROM group_administrators WHERE group_id = $1
                """,
                    group_id,
                )
            ]

            # Remove admins not in the new list
            removed_admins = set(current_admins) - set(admin_ids)
            if removed_admins:
                await conn.execute(
                    """
                    DELETE FROM group_administrators
                    WHERE group_id = $1 AND admin_id = ANY($2)
                """,
                    group_id,
                    list(removed_admins),
                )

            # Add new admins
            new_admins = set(admin_ids) - set(current_admins)
            if new_admins:
                # First ensure all admins exist in administrators table
                for admin_id in new_admins:
                    # Initialize new admin if doesn't exist
                    await admin_operations.initialize_new_admin(admin_id)

                # Then add them as group administrators
                await conn.executemany(
                    """
                    INSERT INTO group_administrators (group_id, admin_id)
                    VALUES ($1, $2)
                    """,
                    [(group_id, admin_id) for admin_id in new_admins],
                )

            # Update group last_active
            await conn.execute(
                """
                UPDATE groups SET last_active = NOW()
                WHERE group_id = $1
                """,
                group_id,
            )

            # Update Mixpanel profiles for affected admins
            for admin_id in removed_admins | new_admins:
                # Get updated count of managed groups
                managed_groups_count = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM group_administrators
                    WHERE admin_id = $1
                    """,
                    admin_id,
                )

                # Update Mixpanel profile
                mp.people_set(
                    admin_id,
                    {
                        "managed_groups_count": managed_groups_count,
                        "$last_group_change": "removed"
                        if admin_id in removed_admins
                        else "added",
                        "$last_group_change_date": "NOW()",
                    },
                )
