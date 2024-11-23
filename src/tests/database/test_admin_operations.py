import pytest

from ...app.database import (
    get_admin,
    get_admin_credits,
    get_spam_deletion_state,
    initialize_new_admin,
    save_admin,
    toggle_spam_deletion,
)
from ...app.database.constants import INITIAL_CREDITS


@pytest.mark.asyncio
async def test_save_and_get_user(patched_db_conn, clean_db, sample_user):
    """Test saving and retrieving a user"""
    async with clean_db.acquire() as conn:
        # Save the user
        await save_admin(sample_user)

        # Retrieve the user
        retrieved_user = await get_admin(sample_user.admin_id)

        # Assertions
        assert retrieved_user is not None
        assert retrieved_user.admin_id == sample_user.admin_id
        assert retrieved_user.username == sample_user.username
        assert retrieved_user.credits == sample_user.credits
        assert retrieved_user.delete_spam == sample_user.delete_spam


@pytest.mark.asyncio
async def test_initialize_new_user(patched_db_conn, clean_db):
    """Test initializing a new user"""
    user_id = 789012

    # Initialize new user
    result = await initialize_new_admin(user_id)

    # Assertions
    assert result is True

    # Verify the user was created with initial credits
    user = await get_admin(user_id)
    assert user is not None
    assert user.credits == INITIAL_CREDITS
    assert user.delete_spam is True


@pytest.mark.asyncio
async def test_toggle_spam_deletion(patched_db_conn, clean_db, sample_user):
    """Test toggling spam deletion setting"""
    # Save the user first
    await save_admin(sample_user)

    # Initial state should be True
    initial_state = await get_spam_deletion_state(sample_user.admin_id)
    assert initial_state is True

    # Toggle to False
    new_state = await toggle_spam_deletion(sample_user.admin_id)
    assert new_state is False

    # Verify state is False
    current_state = await get_spam_deletion_state(sample_user.admin_id)
    assert current_state is False

    # Toggle back to True
    new_state = await toggle_spam_deletion(sample_user.admin_id)
    assert new_state is True

    # Verify state is True again
    current_state = await get_spam_deletion_state(sample_user.admin_id)
    assert current_state is True


@pytest.mark.asyncio
async def test_get_spam_deletion_state_default(patched_db_conn, clean_db):
    """Test getting spam deletion state for non-existent user"""
    # Should return True (default) for non-existent user
    state = await get_spam_deletion_state(999999)
    assert state is True


@pytest.mark.asyncio
async def test_get_spam_deletion_state(patched_db_conn, clean_db, sample_user):
    """Test getting spam deletion state"""
    # Save user with delete_spam=False
    sample_user.delete_spam = False
    await save_admin(sample_user)

    # Get state
    state = await get_spam_deletion_state(sample_user.admin_id)
    assert state is False


@pytest.mark.asyncio
async def test_toggle_spam_deletion_non_existent_admin(patched_db_conn, clean_db):
    """Test toggling spam deletion setting for non-existent admin""" ""
    admin_id = 999999

    # Toggle spam deletion for non-existent admin
    new_state = await toggle_spam_deletion(admin_id)

    assert new_state is None


@pytest.mark.asyncio
async def test_get_user_credits(patched_db_conn, clean_db, sample_user):
    """Test retrieving user credits"""
    # Save the user first
    await save_admin(sample_user)

    # Retrieve user credits
    credits = await get_admin_credits(sample_user.admin_id)

    # Assertions
    assert credits == sample_user.credits
