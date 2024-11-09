from datetime import datetime

import pytest

import common.database
from common.database.constants import INITIAL_CREDITS
from common.database.models import User
from common.database.user_operations import (
    add_credits,
    deduct_credits,
    get_spam_deletion_state,
    get_user,
    initialize_new_user,
    save_user,
    toggle_spam_deletion,
)


@pytest.fixture
def sample_user():
    return User(
        user_id=123456,
        username="testuser",
        credits=50,
        is_active=True,
        delete_spam=True,
        created_at=datetime.now(),
        last_updated=datetime.now(),
    )


@pytest.mark.asyncio
async def test_save_and_get_user(patched_redis_conn, clean_redis, sample_user):
    """Test saving and retrieving a user"""
    # Save the user
    await save_user(sample_user)

    # Retrieve the user
    retrieved_user = await get_user(sample_user.user_id)

    # Assertions
    assert retrieved_user is not None
    assert retrieved_user.user_id == sample_user.user_id
    assert retrieved_user.username == sample_user.username
    assert retrieved_user.credits == sample_user.credits
    assert retrieved_user.delete_spam == sample_user.delete_spam


@pytest.mark.asyncio
async def test_deduct_credits(patched_redis_conn, clean_redis, sample_user):
    """Test deducting credits"""
    # Save the user first to ensure the record exists
    await save_user(sample_user)

    # Deduct credits
    result = await deduct_credits(sample_user.user_id, 20)

    # Assertions
    assert result is True


@pytest.mark.asyncio
async def test_initialize_new_user(patched_redis_conn, clean_redis):
    """Test initializing a new user"""
    print("Checking if Redis is empty")
    assert not await common.database.redis.keys("*")

    user_id = 789012

    # Initialize new user
    result = await initialize_new_user(user_id)

    # Assertions
    assert result is True

    # Verify the user was created with initial credits and default delete_spam setting
    user = await get_user(user_id)
    assert user is not None
    assert user.credits == INITIAL_CREDITS
    assert user.delete_spam is True  # Default should be True


@pytest.mark.asyncio
async def test_add_credits(patched_redis_conn, clean_redis, sample_user):
    """Test adding credits"""
    # Save the user first
    await save_user(sample_user)

    # Add credits
    await add_credits(sample_user.user_id, 30)

    # Retrieve updated user
    updated_user = await get_user(sample_user.user_id)

    # Assertions
    assert updated_user.credits == sample_user.credits + 30


@pytest.mark.asyncio
async def test_toggle_spam_deletion(patched_redis_conn, clean_redis, sample_user):
    """Test toggling spam deletion setting"""
    # Save the user first
    await save_user(sample_user)

    # Initial state should be True
    initial_state = await get_spam_deletion_state(sample_user.user_id)
    assert initial_state is True

    # Toggle to False
    new_state = await toggle_spam_deletion(sample_user.user_id)
    assert new_state is False

    # Verify state is False
    current_state = await get_spam_deletion_state(sample_user.user_id)
    assert current_state is False

    # Toggle back to True
    new_state = await toggle_spam_deletion(sample_user.user_id)
    assert new_state is True

    # Verify state is True again
    current_state = await get_spam_deletion_state(sample_user.user_id)
    assert current_state is True


@pytest.mark.asyncio
async def test_get_spam_deletion_state_default(patched_redis_conn, clean_redis):
    """Test getting spam deletion state for non-existent user"""
    # Should return True (default) for non-existent user
    state = await get_spam_deletion_state(999999)
    assert state is True


@pytest.mark.asyncio
async def test_get_spam_deletion_state(patched_redis_conn, clean_redis, sample_user):
    """Test getting spam deletion state"""
    # Save user with delete_spam=False
    sample_user.delete_spam = False
    await save_user(sample_user)

    # Get state
    state = await get_spam_deletion_state(sample_user.user_id)
    assert state is False
