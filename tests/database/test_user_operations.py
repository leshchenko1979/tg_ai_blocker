from datetime import datetime

import common.database
import pytest
from common.database.constants import INITIAL_CREDITS
from common.database.models import User
from common.database.user_operations import (add_credits, deduct_credits,
                                             get_user, initialize_new_user,
                                             save_user)


@pytest.fixture
def sample_user():
    return User(
        user_id=123456,
        username="testuser",
        credits=50,
        is_active=True,
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

    # Verify the user was created with initial credits
    user = await get_user(user_id)
    assert user is not None
    assert user.credits == INITIAL_CREDITS


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
