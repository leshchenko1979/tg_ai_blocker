from datetime import datetime
from typing import List, Optional

from ..bot import bot
from ..yandex_logging import get_yandex_logger, log_function_call
from .models import Group
from .redis_connection import redis

logger = get_yandex_logger(__name__)


@log_function_call(logger)
async def save_group(group: Group) -> None:
    """Save group to Redis with improved type handling"""
    pipeline = redis.pipeline()

    # Save main group data in hash
    pipeline.hset(
        f"group:{group.group_id}",
        mapping={
            "is_moderation_enabled": int(group.is_moderation_enabled),
            "created_at": group.created_at.isoformat(),
            "last_updated": datetime.now().isoformat(),
        },
    )

    # Save admin_ids and unique_users in separate sets
    pipeline.delete(f"group:{group.group_id}:admins")
    pipeline.delete(f"group:{group.group_id}:members")

    if group.admin_ids:
        await pipeline.sadd(f"group:{group.group_id}:admins", *group.admin_ids)

    if group.member_ids:
        await pipeline.sadd(f"group:{group.group_id}:members", *group.member_ids)

    await pipeline.execute()


@log_function_call(logger)
async def get_group(group_id: int) -> Optional[Group]:
    """Retrieve group information"""
    group_data = await redis.hgetall(f"group:{group_id}")
    if not group_data:
        return None

    # Get admin_ids and unique_users from sets
    admin_ids = [int(x) for x in await redis.smembers(f"group:{group_id}:admins") if x]
    member_ids = [
        int(x) for x in await redis.smembers(f"group:{group_id}:members") if x
    ]

    return Group(
        group_id=group_id,
        admin_ids=admin_ids,
        is_moderation_enabled=bool(int(group_data.get("is_moderation_enabled", 0))),
        member_ids=member_ids,
        created_at=datetime.fromisoformat(
            group_data.get("created_at", datetime.now().isoformat())
        ),
        last_updated=datetime.fromisoformat(
            group_data.get("last_updated", datetime.now().isoformat())
        ),
    )


@log_function_call(logger)
async def set_group_moderation(group_id: int, enabled: bool) -> None:
    """Enable/disable moderation for a group"""
    await redis.hset(
        f"group:{group_id}", mapping={"is_moderation_enabled": int(enabled)}
    )


@log_function_call(logger)
async def is_moderation_enabled(group_id: int) -> bool:
    """Check if moderation is enabled for a group"""
    enabled = await redis.hget(f"group:{group_id}", "is_moderation_enabled")
    return bool(int(enabled or 0))


@log_function_call(logger)
async def get_paying_admins(group_id: int) -> List[int]:
    """Get list of admins with positive credits"""
    admin_ids = await redis.smembers(f"group:{group_id}:admins")
    paying_admins = []

    for admin in admin_ids:
        credits_raw = await redis.hget(f"user:{admin}", "credits")
        credits = int(credits_raw)

        if credits > 0:
            paying_admins.append(int(admin))

    return paying_admins


@log_function_call(logger)
async def deduct_credits_from_admins(group_id: int, amount: int) -> bool:
    """Deduct credits from the admin with the highest balance"""
    from .user_operations import deduct_credits

    # Get all admins and their balances in one request
    admin_ids = await redis.smembers(f"group:{group_id}:admins")
    pipeline = redis.pipeline()
    for admin in admin_ids:
        pipeline.hget(f"user:{admin}", "credits")

    balances = await pipeline.execute()

    # Find the admin with the highest balance
    highest_balance_admin = None
    highest_balance = 0

    for admin, balance in zip(admin_ids, balances):
        balance = int(balance)
        if balance > highest_balance:
            highest_balance_admin = admin
            highest_balance = balance

    # Deduct from the admin with the highest balance
    if highest_balance_admin and highest_balance >= amount:
        if await deduct_credits(highest_balance_admin, amount):
            return True

    return False


@log_function_call(logger)
async def get_user_groups(user_id: int) -> List[int]:
    """Get list of groups where user is an admin"""
    groups = []
    cursor = 0
    pattern = "group:*:admins"

    while True:
        cursor, keys = await redis.scan(cursor, match=pattern)
        for key in keys:
            if await redis.sismember(key, user_id):
                # Extract group_id from key (format: group:{id}:admins)
                group_id = int(key.split(":")[1])
                groups.append(group_id)

        if cursor == 0:  # When cursor returns to 0, scanning is complete
            break

    return groups


@log_function_call(logger)
async def get_user_admin_groups(user_id: int):
    """
    Get list of groups where user is an admin

    Args:
        user_id: User ID

    Returns:
        list: List of dictionaries with group information (id, title, is_moderation_enabled)
    """
    groups = []
    cursor = 0

    while True:
        cursor, keys = await redis.scan(cursor, match="group:*")
        if not keys:
            if cursor == 0:
                break
            continue

        pipeline = redis.pipeline()
        group_ids = []

        for key in keys:
            if key.count(":") == 1:
                group_id = int(key.split(":")[1])
                group_ids.append(group_id)
                pipeline.sismember(f"group:{group_id}:admins", user_id)
                pipeline.hget(f"group:{group_id}", "is_moderation_enabled")

        if not group_ids:
            if cursor == 0:
                break
            continue

        results = await pipeline.execute()

        # Process results in pairs (is_admin, moderation_status)
        for i in range(0, len(results), 2):
            is_admin = results[i]
            moderation_status = results[i + 1]
            group_id = group_ids[i // 2]

            if is_admin:
                try:
                    chat = await bot.get_chat(group_id)
                    groups.append(
                        {
                            "id": group_id,
                            "title": chat.title,
                            "is_moderation_enabled": bool(int(moderation_status or 0)),
                        }
                    )
                except Exception as e:
                    logger.error(f"Error getting chat {group_id}: {e}", exc_info=True)
                    continue

        if cursor == 0:
            break

    return groups


@log_function_call(logger)
async def ensure_group_exists(group_id: int, admin_ids: List[int]) -> None:
    """Create group if it doesn't exist"""
    exists = await redis.exists(f"group:{group_id}")
    if not exists:
        pipeline = redis.pipeline()

        pipeline.hset(
            f"group:{group_id}",
            mapping={
                "is_moderation_enabled": 1,
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
            },
        )
        if admin_ids:
            await pipeline.sadd(f"group:{group_id}:admins", *admin_ids)
        await pipeline.execute()


@log_function_call(logger)
async def update_group_admins(group_id: int, admin_ids: List[int]) -> None:
    """Update list of group administrators"""
    pipeline = redis.pipeline()

    pipeline.delete(f"group:{group_id}:admins")
    if admin_ids:
        pipeline.sadd(f"group:{group_id}:admins", *admin_ids)
    pipeline.hset(f"group:{group_id}", "last_updated", datetime.now().isoformat())
    await pipeline.execute()


@log_function_call(logger)
async def is_user_in_group(group_id: int, user_id: int) -> bool:
    """Check if user is in group"""
    return bool(await redis.sismember(f"group:{group_id}:members", user_id))


@log_function_call(logger)
async def add_unique_user(group_id: int, user_id: int) -> None:
    """Add unique user to group"""
    await redis.sadd(f"group:{group_id}:members", user_id)


@log_function_call(logger)
async def remove_user_from_group(user_id: int, group_id: Optional[int] = None) -> None:
    """
    Remove a user from a group or all groups in Redis

    Args:
        user_id: ID пользователя для удаления
        group_id: ID группы (если None, удаляет пользователя из всех групп)
    """
    if group_id is not None:
        # Удаление пользователя из конкретной группы
        pipeline = redis.pipeline()
        pipeline.srem(f"group:{group_id}:members", user_id)
        pipeline.hset(f"group:{group_id}", "last_updated", datetime.now().isoformat())
        await pipeline.execute()
    else:
        # Удаление пользователя из всех групп
        cursor = 0
        pattern = "group:*:members"

        while True:
            cursor, keys = await redis.scan(cursor, match=pattern)

            if keys:
                pipeline = redis.pipeline()
                for key in keys:
                    # Удаление пользователя из каждой группы
                    pipeline.srem(key, user_id)
                    # Обновление времени последнего изменения для каждой группы
                    group_id = key.split(":")[1]
                    pipeline.hset(
                        f"group:{group_id}", "last_updated", datetime.now().isoformat()
                    )

                await pipeline.execute()

            if cursor == 0:
                break
