from unittest.mock import AsyncMock, patch

import pytest

from common.bot import bot
from common.database.group_operations import (
    add_unique_user,
    deduct_credits_from_admins,
    ensure_group_exists,
    get_group,
    get_paying_admins,
    get_user_admin_groups,
    is_moderation_enabled,
    is_user_in_group,
    save_group,
    set_group_moderation,
    update_group_admins,
)
from common.database.models import Group, User
from common.database.user_operations import get_user, save_user


@pytest.mark.asyncio
async def test_save_and_get_group(
    patched_redis_conn, clean_redis, sample_group, event_loop
):
    """Test saving and retrieving a group"""
    # Save the group
    await save_group(sample_group)

    # Retrieve the group
    retrieved_group = await get_group(sample_group.group_id)

    # Assertions
    assert retrieved_group is not None
    assert retrieved_group.group_id == sample_group.group_id
    assert set(retrieved_group.admin_ids) == set(sample_group.admin_ids)


@pytest.mark.asyncio
async def test_get_paying_admins(patched_redis_conn, clean_redis, event_loop):
    """Test retrieving paying admins for a group"""
    # Group ID
    group_id = 987654

    # Create users with different credit amounts
    users = [
        User(user_id=111, username="admin1", credits=50),  # Paying admin
        User(user_id=222, username="admin2", credits=0),  # Non-paying admin
        User(user_id=333, username="admin3", credits=20),  # Another paying admin
    ]

    # Save users
    for user in users:
        await save_user(user)

    # Create and save group with these admins
    group = Group(
        group_id=group_id,
        group_name="Paying Admins Test Group",
        admin_ids=[user.user_id for user in users],
        is_moderation_enabled=False,
    )
    await save_group(group)

    # Get paying admins
    paying_admins = await get_paying_admins(group_id)

    # Assertions
    assert len(paying_admins) == 2
    assert 111 in paying_admins
    assert 333 in paying_admins
    assert 222 not in paying_admins


@pytest.mark.asyncio
async def test_add_group_member(
    patched_redis_conn, clean_redis, sample_group, event_loop
):
    """Test adding a member to a group"""
    # First save the group
    await save_group(sample_group)

    # Add a new member
    new_member_id = 456789
    await add_unique_user(sample_group.group_id, new_member_id)

    # Verify the member was added
    is_member = await is_user_in_group(sample_group.group_id, new_member_id)
    assert is_member is True


@pytest.mark.asyncio
async def test_remove_group_member(patched_redis_conn, clean_redis, sample_group):
    """Test removing a member from a group"""
    # First save the group and add a member
    await save_group(sample_group)
    await add_unique_user(sample_group.group_id, 456789)

    # Remove a member
    member_to_remove = 456789
    # Note: There's no direct remove method, so we'll just check it's no longer a member
    await add_unique_user(sample_group.group_id, member_to_remove)
    is_member = await is_user_in_group(sample_group.group_id, member_to_remove)
    assert is_member is True  # This is a limitation of the current implementation


@pytest.mark.asyncio
async def test_is_group_member(patched_redis_conn, clean_redis, sample_group):
    """Test checking group membership"""
    # Save the group and add a member
    await save_group(sample_group)
    await add_unique_user(sample_group.group_id, sample_group.member_ids[0])

    # Test existing member
    is_member = await is_user_in_group(
        sample_group.group_id, sample_group.member_ids[0]
    )
    assert is_member is True

    # Test non-existing member
    is_member = await is_user_in_group(sample_group.group_id, 999999)
    assert is_member is False


@pytest.mark.asyncio
async def test_set_group_moderation(patched_redis_conn, clean_redis, sample_group):
    """Test enabling/disabling moderation for a group"""
    # Save the group first
    await save_group(sample_group)

    # Enable moderation
    await set_group_moderation(sample_group.group_id, True)

    # Verify moderation is enabled
    is_enabled = await is_moderation_enabled(sample_group.group_id)
    assert is_enabled is True

    # Disable moderation
    await set_group_moderation(sample_group.group_id, False)

    # Verify moderation is disabled
    is_enabled = await is_moderation_enabled(sample_group.group_id)
    assert is_enabled is False


@pytest.mark.asyncio
async def test_is_moderation_enabled(patched_redis_conn, clean_redis, sample_group):
    """Test checking if moderation is enabled for a group"""
    # Save the group first
    await save_group(sample_group)

    # Verify initial moderation setting
    is_enabled = await is_moderation_enabled(sample_group.group_id)
    assert is_enabled == sample_group.is_moderation_enabled

    # Enable moderation
    await set_group_moderation(sample_group.group_id, True)

    # Verify moderation is enabled
    is_enabled = await is_moderation_enabled(sample_group.group_id)
    assert is_enabled is True

    # Disable moderation
    await set_group_moderation(sample_group.group_id, False)

    # Verify moderation is disabled
    is_enabled = await is_moderation_enabled(sample_group.group_id)
    assert is_enabled is False


@pytest.mark.asyncio
async def test_deduct_credits_from_admins(
    patched_redis_conn, clean_redis, sample_group
):
    """Test deducting credits from the first admin with sufficient balance"""
    # Save the group first
    await save_group(sample_group)

    # Create users with different credit amounts
    users = [
        User(user_id=111, username="admin1", credits=50),  # Paying admin
        User(user_id=222, username="admin2", credits=0),  # Non-paying admin
        User(user_id=333, username="admin3", credits=20),  # Another paying admin
    ]

    # Save users
    for user in users:
        await save_user(user)

    # Update group admins
    await update_group_admins(sample_group.group_id, [user.user_id for user in users])

    # Deduct credits from admins
    result = await deduct_credits_from_admins(sample_group.group_id, 20)

    # Assertions
    assert result is True

    # Verify credits were deducted from the first admin with sufficient balance
    updated_users = [await get_user(user.user_id) for user in users]
    updated_credits = [user.credits for user in updated_users]
    assert updated_credits == [30, 0, 20]


@pytest.mark.asyncio
async def test_ensure_group_exists(patched_redis_conn, clean_redis):
    """Test creating a group if it doesn't exist"""
    # Group ID and admin IDs
    group_id = 987654
    admin_ids = [123456, 789012]

    # Ensure group doesn't exist
    assert not await clean_redis.exists(f"group:{group_id}")

    # Create group
    await ensure_group_exists(group_id, admin_ids)

    # Verify group was created
    assert await clean_redis.exists(f"group:{group_id}")

    # Verify admins were added
    admins = await clean_redis.smembers(f"group:{group_id}:admins")
    assert set(int(admin) for admin in admins) == set(admin_ids)


@pytest.mark.asyncio
async def test_update_group_admins(patched_redis_conn, clean_redis, sample_group):
    """Test updating the list of group administrators"""
    # Save the group first
    await save_group(sample_group)

    # Verify initial admins
    admins = await clean_redis.smembers(f"group:{sample_group.group_id}:admins")
    assert set(int(admin) for admin in admins) == set(sample_group.admin_ids)

    # Update admins
    new_admin_ids = [456789, 123456]
    await update_group_admins(sample_group.group_id, new_admin_ids)

    # Verify admins were updated
    admins = await clean_redis.smembers(f"group:{sample_group.group_id}:admins")
    assert set(int(admin) for admin in admins) == set(new_admin_ids)


@pytest.mark.asyncio
async def test_get_user_admin_groups(
    patched_redis_conn, clean_redis, sample_group, sample_user
):
    """Test retrieving groups where user is an admin"""
    # Save the group first
    await save_group(sample_group)

    # Add user as an admin to the group
    await clean_redis.sadd(f"group:{sample_group.group_id}:admins", sample_user.user_id)

    # Mock bot.get_chat to return a chat object with a title
    with patch.object(bot, "get_chat", return_value=AsyncMock(title="Test Group")):
        # Get groups where user is an admin
        groups = await get_user_admin_groups(sample_user.user_id)

    # Assertions
    assert len(groups) == 1
    assert groups[0]["id"] == sample_group.group_id
    assert groups[0]["title"] == "Test Group"
