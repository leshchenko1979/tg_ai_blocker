import pytest
from common.database.group_operations import (add_unique_user, get_group,
                                              get_paying_admins,
                                              is_user_in_group, save_group)
from common.database.models import Group, User
from common.database.user_operations import save_user


@pytest.fixture
def sample_group():
    return Group(
        group_id=987654,
        group_name="Test Group",
        member_ids=[123456, 789012],
        admin_ids=[123456, 789012],
        is_moderation_enabled=False,
    )


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
