from datetime import datetime
from typing import Optional

from ..yandex_logging import get_yandex_logger, log_function_call
from .constants import INITIAL_CREDITS
from .group_operations import get_user_groups
from .models import User
from .redis_connection import redis

logger = get_yandex_logger(__name__)


@log_function_call(logger)
async def save_user(user: User) -> None:
    """Save user to Redis with improved type handling"""
    await redis.hset(
        f"user:{user.user_id}",
        mapping={
            "username": user.username or "",
            "credits": user.credits,
            "is_active": int(user.is_active),
            "created_at": user.created_at.isoformat(),
            "last_updated": datetime.now().isoformat(),
        },
    )


@log_function_call(logger)
async def get_user_credits(user_id: int) -> int:
    """Retrieve user credits with safe type conversion"""
    try:
        credits_raw = await redis.hget(f"user:{user_id}", "credits")
        return int(credits_raw.decode()) if credits_raw else INITIAL_CREDITS
    except (TypeError, ValueError) as e:
        logger.error(f"Error getting user credits: {e}")
        return INITIAL_CREDITS


@log_function_call(logger)
async def deduct_credits(user_id: int, amount: int) -> bool:
    """Deduct credits from user. Returns True if successful"""
    try:
        # Get current balance
        current_credits = int(await redis.hget(f"user:{user_id}", "credits") or 0)

        if current_credits < amount:
            return False

        await redis.hincrby(f"user:{user_id}", "credits", -amount)
        return True
    except Exception as e:
        logger.error(f"Error deducting credits: {e}", exc_info=True)
        raise


@log_function_call(logger)
async def initialize_new_user(user_id: int) -> bool:
    """Initialize a new user with initial credits"""
    pipeline = redis.pipeline()

    # Check existence and create atomically
    pipeline.exists(f"user:{user_id}")
    pipeline.hset(
        f"user:{user_id}",
        mapping={
            "credits": INITIAL_CREDITS,
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
        },
    )

    results = await pipeline.execute()
    return not results[0]  # Return True if user was created


@log_function_call(logger)
async def get_user(user_id: int) -> Optional[User]:
    """Retrieve user information"""
    user_data = await redis.hgetall(f"user:{user_id}")
    if not user_data:
        return None

    # Safely handle datetime fields with fallback
    now = datetime.now()
    created_at_str = user_data.get("created_at", now.isoformat())
    last_updated_str = user_data.get("last_updated", now.isoformat())

    try:
        created_at = datetime.fromisoformat(created_at_str)
        last_updated = datetime.fromisoformat(last_updated_str)
    except (TypeError, ValueError):
        # If parsing fails, use current time
        created_at = now
        last_updated = now

    return User(
        user_id=user_id,
        username=user_data.get("username"),
        credits=int(user_data.get("credits", 0)),
        is_active=bool(int(user_data.get("is_active", 1))),
        created_at=created_at,
        last_updated=last_updated,
    )


@log_function_call(logger)
async def add_credits(user_id: int, amount: int) -> None:
    """Add credits to user and enable moderation in their groups"""
    await redis.hincrby(f"user:{user_id}", "credits", amount)

    # Get all groups where user is an admin
    user_groups = await get_user_groups(user_id)

    # Enable moderation in each group
    from .group_operations import set_group_moderation

    for group_id in user_groups:
        await set_group_moderation(group_id, True)
