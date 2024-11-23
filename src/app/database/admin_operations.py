from typing import Optional

from ..common.yandex_logging import get_yandex_logger, log_function_call
from .constants import INITIAL_CREDITS
from .models import Administrator
from .postgres_connection import get_pool

logger = get_yandex_logger(__name__)


@log_function_call(logger)
async def save_admin(admin: Administrator) -> None:
    """Save administrator to PostgreSQL"""
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
            admin.admin_id,
            admin.username,
            admin.credits,
            admin.delete_spam,
            admin.created_at,
            admin.last_updated,
        )


@log_function_call(logger)
async def get_admin(admin_id: int) -> Optional[Administrator]:
    """Retrieve administrator information from PostgreSQL"""
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

        return Administrator(
            admin_id=row["admin_id"],
            username=row["username"],
            credits=row["credits"],
            is_active=True,  # Always true if record exists
            delete_spam=row["delete_spam"],
            created_at=row["created_at"],
            last_updated=row["last_active"],
        )


@log_function_call(logger)
async def get_admin_credits(admin_id: int) -> int:
    """Retrieve administrator credits"""
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
async def initialize_new_admin(admin_id: int) -> bool:
    """Initialize a new administrator with initial credits"""
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
async def toggle_spam_deletion(admin_id: int) -> bool:
    """Toggle spam deletion setting for administrator. Returns new state"""
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
    """Get current spam deletion state for administrator"""
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


@log_function_call(logger)
async def get_spent_credits_last_week(admin_id: int) -> int:
    """Get total spent credits for the last 7 days"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        spent_credits = await conn.fetchval(
            """
            SELECT COALESCE(SUM(ABS(amount)), 0)
            FROM transactions
            WHERE admin_id = $1
            AND amount < 0
            AND created_at >= NOW() - INTERVAL '7 days'
        """,
            admin_id,
        )
        return spent_credits
