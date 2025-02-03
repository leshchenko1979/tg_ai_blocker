import logging
from typing import Dict, List, Optional

from ..common.bot import bot
from .constants import INITIAL_CREDITS
from .models import Group
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


async def deduct_credits_from_admins(group_id: int, amount: int) -> bool:
    """Deduct credits from the admin with the highest balance"""
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
                return False

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

            return True


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
    """Update group administrators and create group if it doesn't exist"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "CALL update_group_admins($1, $2::bigint[], $3)",
            group_id,
            admin_ids,
            INITIAL_CREDITS,
        )
