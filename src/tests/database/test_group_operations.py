import pytest

from app.common.database.group_operations import (
    add_member,
    get_paying_admins,
    is_member_in_group,
    is_moderation_enabled,
    remove_member_from_group,
    set_group_moderation,
)
from app.common.database.models import User


@pytest.mark.asyncio
async def test_get_paying_admins(patched_db_conn, clean_db):
    """Test retrieving paying admins for a group"""
    async with clean_db.acquire() as conn:
        group_id = 987654

        # Create users with different credit amounts
        users = [
            User(admin_id=111, username="admin1", credits=50),  # Paying admin
            User(admin_id=222, username="admin2", credits=0),  # Non-paying admin
            User(admin_id=333, username="admin3", credits=20),  # Another paying admin
        ]

        # Save users to administrators table
        for user in users:
            await conn.execute(
                """
                INSERT INTO administrators (admin_id, username, credits)
                VALUES ($1, $2, $3)
                ON CONFLICT DO NOTHING
            """,
                user.admin_id,
                user.username,
                user.credits,
            )

        # Create group directly in database
        await conn.execute(
            """
            INSERT INTO groups (group_id)
            VALUES ($1)
        """,
            group_id,
        )

        # Add admins to group directly
        for user in users:
            await conn.execute(
                """
                INSERT INTO group_administrators (group_id, admin_id)
                VALUES ($1, $2)
            """,
                group_id,
                user.admin_id,
            )

        # Get paying admins
        paying_admins = await get_paying_admins(group_id)

        # Assertions
        assert len(paying_admins) == 2
        assert 111 in paying_admins
        assert 333 in paying_admins
        assert 222 not in paying_admins


@pytest.mark.asyncio
async def test_add_group_member(patched_db_conn, clean_db):
    """Test adding a member to a group"""
    async with clean_db.acquire() as conn:
        group_id = 987654
        new_member_id = 456789

        # Create group directly in database
        await conn.execute(
            """
            INSERT INTO groups (group_id)
            VALUES ($1)
        """,
            group_id,
        )

        # Add a new member
        await add_member(group_id, new_member_id)

        # Verify the member was added
        is_member = await is_member_in_group(group_id, new_member_id)
        assert is_member is True


@pytest.mark.asyncio
async def test_remove_group_member(patched_db_conn, clean_db):
    """Test removing a member from a group"""
    async with clean_db.acquire() as conn:
        group_id = 987654
        member_to_remove = 456789

        await conn.execute(
            """
            INSERT INTO groups (group_id)
            VALUES ($1)
        """,
            group_id,
        )

        # Add member directly to database
        await conn.execute(
            """
            INSERT INTO approved_members (group_id, member_id)
            VALUES ($1, $2)
        """,
            group_id,
            member_to_remove,
        )

        # Remove the member
        await remove_member_from_group(member_to_remove, group_id)

        # Verify member was removed
        is_member = await is_member_in_group(group_id, member_to_remove)
        assert is_member is False


@pytest.mark.asyncio
async def test_set_group_moderation(patched_db_conn, clean_db):
    """Test enabling/disabling moderation for a group"""
    async with clean_db.acquire() as conn:
        group_id = 987654

        # Add group directly to database
        await conn.execute(
            """
            INSERT INTO groups (group_id, moderation_enabled)
            VALUES ($1, $2)
        """,
            group_id,
            False,
        )

        # Enable moderation
        await set_group_moderation(group_id, True)

        # Verify moderation is enabled
        is_enabled = await is_moderation_enabled(group_id)
        assert is_enabled is True
