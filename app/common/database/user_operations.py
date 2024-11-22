from datetime import datetime
from typing import List, Optional

from ..yandex_logging import get_yandex_logger, log_function_call
from .constants import INITIAL_CREDITS
from .models import User
from .postgres_connection import get_pool

logger = get_yandex_logger(__name__)


@log_function_call(logger)
async def save_user(user: User) -> None:
    """Save user to PostgreSQL"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO administrators (
                admin_id, username, credits, delete_spam, created_at, last_active
            ) VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (admin_id) DO UPDATE SET
                username = $2,
                credits = $3,
                delete_spam = $4,
                last_active = $6
        """,
            user.admin_id,
            user.username,
            user.credits,
            user.delete_spam,
            user.created_at,
            user.last_updated,
        )


@log_function_call(logger)
async def get_user(admin_id: int) -> Optional[User]:
    """Retrieve user information from PostgreSQL"""
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

        return User(
            admin_id=row["admin_id"],
            username=row["username"],
            credits=row["credits"],
            is_active=True,  # Always true if record exists
            delete_spam=row["delete_spam"],
            created_at=row["created_at"],
            last_updated=row["last_active"],
        )


@log_function_call(logger)
async def get_user_credits(admin_id: int) -> int:
    """Retrieve user credits"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        credits = await conn.fetchval(
            """
            SELECT credits FROM administrators WHERE admin_id = $1
        """,
            admin_id,
        )
        return credits if credits is not None else INITIAL_CREDITS


@log_function_call(logger)
async def deduct_credits(admin_id: int, amount: int) -> bool:
    """Deduct credits from user. Returns True if successful"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            current_credits = await conn.fetchval(
                """
                SELECT credits FROM administrators WHERE admin_id = $1
            """,
                admin_id,
            )

            if current_credits is None or current_credits < amount:
                return False

            await conn.execute(
                """
                UPDATE administrators
                SET credits = credits - $1, last_active = NOW()
                WHERE admin_id = $2
            """,
                amount,
                admin_id,
            )

            # Record transaction
            await conn.execute(
                """
                INSERT INTO transactions (admin_id, amount, type, description)
                VALUES ($1, $2, 'deduct', 'Credit deduction')
            """,
                admin_id,
                -amount,
            )

            return True


@log_function_call(logger)
async def initialize_new_user(admin_id: int) -> bool:
    """Initialize a new user with initial credits"""
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
                    admin_id, credits, delete_spam, created_at, last_active
                ) VALUES ($1, $2, true, NOW(), NOW())
            """,
                admin_id,
                INITIAL_CREDITS,
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


@log_function_call(logger)
async def add_credits(admin_id: int, amount: int) -> None:
    """Add credits to user and enable moderation in their groups. Creates user if doesn't exist."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Check if user exists and create if not
            exists = await conn.fetchval(
                """
                SELECT EXISTS(SELECT 1 FROM administrators WHERE admin_id = $1)
            """,
                admin_id,
            )

            if not exists:
                await conn.execute(
                    """
                    INSERT INTO administrators (
                        admin_id, credits, delete_spam, created_at, last_active
                    ) VALUES ($1, $2, true, NOW(), NOW())
                """,
                    admin_id,
                    0,
                )  # Initialize with 0 credits before adding new amount

            # Add credits to user
            await conn.execute(
                """
                UPDATE administrators
                SET credits = credits + $1, last_active = NOW()
                WHERE admin_id = $2
            """,
                amount,
                admin_id,
            )

            # Record transaction
            await conn.execute(
                """
                INSERT INTO transactions (admin_id, amount, type, description)
                VALUES ($1, $2, 'add', 'Credit addition')
            """,
                admin_id,
                amount,
            )

            # Enable moderation in all user's groups
            await conn.execute(
                """
                UPDATE groups g
                SET moderation_enabled = true, last_active = NOW()
                FROM group_administrators ga
                WHERE g.group_id = ga.group_id AND ga.admin_id = $1
            """,
                admin_id,
            )


@log_function_call(logger)
async def toggle_spam_deletion(admin_id: int) -> bool:
    """Toggle spam deletion setting for user. Returns new state"""
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


@log_function_call(logger)
async def get_spam_deletion_state(admin_id: int) -> bool:
    """Get current spam deletion state for user"""
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
