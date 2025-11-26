import pytest

from app.database import (
    get_admin,
    get_admin_credits,
    get_spam_deletion_state,
    get_spent_credits_last_week,
    initialize_new_admin,
    save_admin,
    toggle_spam_deletion,
)
from app.database.constants import INITIAL_CREDITS


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

    async with clean_db.acquire() as conn:
        # Initialize new user
        result = await initialize_new_admin(user_id)

        # Assertions
        assert result is True

        # Verify the user was created with initial credits
        user = await get_admin(user_id)
        assert user is not None
        assert user.credits == INITIAL_CREDITS
        assert user.delete_spam is False


@pytest.mark.asyncio
async def test_toggle_spam_deletion(patched_db_conn, clean_db, sample_user):
    """Test toggling spam deletion setting"""
    async with clean_db.acquire() as conn:
        # Save the user first
        await save_admin(sample_user)

        # Initial state should be False (new default)
        initial_state = await get_spam_deletion_state(sample_user.admin_id)
        assert initial_state is False

        # Toggle to True
        new_state = await toggle_spam_deletion(sample_user.admin_id)
        assert new_state is True

        # Verify state is True
        current_state = await get_spam_deletion_state(sample_user.admin_id)
        assert current_state is True

        # Toggle back to False
        new_state = await toggle_spam_deletion(sample_user.admin_id)
        assert new_state is False

        # Verify state is False again
        current_state = await get_spam_deletion_state(sample_user.admin_id)
        assert current_state is False


@pytest.mark.asyncio
async def test_get_spam_deletion_state_default(patched_db_conn, clean_db):
    """Test getting spam deletion state for non-existent user"""
    async with clean_db.acquire() as conn:
        # Should return True (default) for non-existent user
        state = await get_spam_deletion_state(999999)
        assert state is True


@pytest.mark.asyncio
async def test_get_spam_deletion_state(patched_db_conn, clean_db, sample_user):
    """Test getting spam deletion state"""
    async with clean_db.acquire() as conn:
        # Save user with delete_spam=False
        sample_user.delete_spam = False
        await save_admin(sample_user)

        # Get state
        state = await get_spam_deletion_state(sample_user.admin_id)
        assert state is False


@pytest.mark.asyncio
async def test_toggle_spam_deletion_non_existent_admin(patched_db_conn, clean_db):
    """Test toggling spam deletion setting for non-existent admin""" ""
    async with clean_db.acquire() as conn:
        admin_id = 999999

        # Toggle spam deletion for non-existent admin
        new_state = await toggle_spam_deletion(admin_id)

        assert new_state is None


@pytest.mark.asyncio
async def test_get_user_credits(patched_db_conn, clean_db, sample_user):
    """Test retrieving user credits"""
    async with clean_db.acquire() as conn:
        # Save the user first
        await save_admin(sample_user)

        # Retrieve user credits
        credits = await get_admin_credits(sample_user.admin_id)

        # Assertions
        assert credits == sample_user.credits


@pytest.mark.asyncio
async def test_get_spent_credits_last_week(patched_db_conn, clean_db):
    """Test tracking spent credits over the last week"""
    admin_id = 12345
    group_id = 98765

    async with clean_db.acquire() as conn:
        # Create test admin and group
        await conn.execute(
            """
            INSERT INTO administrators (admin_id, credits)
            VALUES ($1, $2)
            """,
            admin_id,
            100,
        )

        await conn.execute(
            """
            INSERT INTO groups (group_id)
            VALUES ($1)
            """,
            group_id,
        )

        await conn.execute(
            """
            INSERT INTO group_administrators (group_id, admin_id)
            VALUES ($1, $2)
            """,
            group_id,
            admin_id,
        )

        # Add some transactions with different scenarios
        # Use separate INSERT statements for SQLite compatibility
        transactions = [
            (admin_id, -10, "deduct", "Group moderation credit deduction", "NOW()"),
            (
                admin_id,
                -5,
                "deduct",
                "Group moderation credit deduction",
                "NOW() - INTERVAL '3 days'",
            ),
            (
                admin_id,
                -15,
                "deduct",
                "Group moderation credit deduction",
                "NOW() - INTERVAL '6 days'",
            ),
            (admin_id, -25, "payment", "Stars purchase", "NOW()"),
            (
                admin_id,
                -20,
                "deduct",
                "Group moderation credit deduction",
                "NOW() - INTERVAL '8 days'",
            ),
            (admin_id, 50, "deduct", "Group moderation credit deduction", "NOW()"),
        ]

        for tx in transactions:
            await conn.execute(
                f"""
                INSERT INTO transactions (admin_id, amount, type, description, created_at)
                VALUES ($1, $2, $3, $4, {tx[4]})
                """,
                tx[0],
                tx[1],
                tx[2],
                tx[3],
            )

    # Test the function
    spent_credits = await get_spent_credits_last_week(admin_id)

    # Should sum up only transactions with negative amounts from last 7 days
    assert spent_credits == 55
