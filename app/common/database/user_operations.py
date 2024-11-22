from datetime import datetime
from typing import Optional

from ..yandex_logging import get_yandex_logger, log_function_call
from .constants import INITIAL_CREDITS
from .group_operations import get_admin_groups, set_group_moderation
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
            "delete_spam": int(user.delete_spam),
            "created_at": user.created_at.isoformat(),
            "last_updated": datetime.now().isoformat(),
        },
    )


@log_function_call(logger)
async def get_user_credits(user_id: int) -> int:
    """Retrieve user credits with safe type conversion"""
    try:
        credits = await redis.hget(f"user:{user_id}", "credits")
        return int(credits) if credits else INITIAL_CREDITS
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
            "delete_spam": 1,  # Default to True
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
        delete_spam=bool(int(user_data.get("delete_spam", 1))),
        created_at=created_at,
        last_updated=last_updated,
    )


@log_function_call(logger)
async def add_credits(user_id: int, amount: int) -> None:
    """Add credits to user and enable moderation in their groups"""
    await redis.hincrby(f"user:{user_id}", "credits", amount)

    # Get all groups where user is an admin
    user_groups = await get_admin_groups(user_id)

    # Enable moderation in each group
    pipeline = redis.pipeline()
    for group in user_groups:
        pipeline.hset(f"group:{group['id']}", "is_moderation_enabled", 1)
    await pipeline.execute()


@log_function_call(logger)
async def toggle_spam_deletion(user_id: int) -> bool:
    """Toggle spam deletion setting for user. Returns new state"""
    try:
        # Get current state
        current_state = int(await redis.hget(f"user:{user_id}", "delete_spam") or 1)
        # Toggle state
        new_state = 1 - current_state  # Toggles between 0 and 1
        # Save new state
        await redis.hset(f"user:{user_id}", "delete_spam", new_state)
        return bool(new_state)
    except Exception as e:
        logger.error(f"Error toggling spam deletion: {e}", exc_info=True)
        raise


@log_function_call(logger)
async def get_spam_deletion_state(user_id: int) -> bool:
    """Get current spam deletion state for user"""
    try:
        state = await redis.hget(f"user:{user_id}", "delete_spam")
        return bool(int(state)) if state is not None else True
    except Exception as e:
        logger.error(f"Error getting spam deletion state: {e}")
        return True  # Default to True if error
