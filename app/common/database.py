from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel
from .dp import redis
from .yandex_logging import get_yandex_logger


logger = get_yandex_logger(__name__)

import functools

def log_function_call(func):
    """Декоратор для логирования вызовов функций"""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        logger.debug(f"Вызов функции {func.__name__} с аргументами: {args}, {kwargs}")
        return await func(*args, **kwargs)
    return wrapper

class User(BaseModel):
    """Модель пользователя"""
    user_id: int
    username: Optional[str]
    credits: int = 0
    is_active: bool = True
    created_at: datetime = datetime.now()
    last_updated: datetime = datetime.now()


class Group(BaseModel):
    """Модель группы"""
    group_id: int
    admin_ids: List[int]
    is_moderation_enabled: bool = True
    unique_users: List[int] = []
    created_at: datetime = datetime.now()
    last_updated: datetime = datetime.now()

@log_function_call
async def save_user(user: User) -> None:
    """Сохранение пользователя в Redis"""
    await redis.hset(
        f"user:{user.user_id}",
        mapping={
            "username": user.username or "",
            "credits": user.credits,
            "is_active": int(user.is_active),
            "created_at": user.created_at.isoformat(),
            "last_updated": datetime.now().isoformat()
        }
    )

@log_function_call
async def save_group(group: Group) -> None:
    """Сохранение группы в Redis"""
    # Сохраняем основные данные в hash
    await redis.hset(
        f"group:{group.group_id}",
        mapping={
            "is_moderation_enabled": int(group.is_moderation_enabled),
            "created_at": group.created_at.isoformat(),
            "last_updated": datetime.now().isoformat()
        }
    )
    # Сохраняем admin_ids и unique_users в отдельных sets
    await redis.delete(f"group:{group.group_id}:admins")
    await redis.delete(f"group:{group.group_id}:users")
    if group.admin_ids:
        await redis.sadd(f"group:{group.group_id}:admins", *group.admin_ids)
    if group.unique_users:
        await redis.sadd(f"group:{group.group_id}:users", *group.unique_users)

@log_function_call
async def get_group(group_id: int) -> Optional[Group]:
    """Получение группы из Redis"""
    group_data = await redis.hgetall(f"group:{group_id}")
    if not group_data:
        return None

    # Получаем admin_ids и unique_users из sets
    admin_ids = [int(x) for x in await redis.smembers(f"group:{group_id}:admins")]
    unique_users = [int(x) for x in await redis.smembers(f"group:{group_id}:users")]

    return Group(
        group_id=group_id,
        admin_ids=admin_ids,
        is_moderation_enabled=bool(int(group_data["is_moderation_enabled"])),
        unique_users=unique_users,
        created_at=datetime.fromisoformat(group_data["created_at"]),
        last_updated=datetime.fromisoformat(group_data["last_updated"])
    )

@log_function_call
async def add_unique_user(group_id: int, user_id: int) -> None:
    """Добавление уникального пользователя в группу"""
    await redis.sadd(f"group:{group_id}:users", user_id)

@log_function_call
async def is_user_in_group(group_id: int, user_id: int) -> bool:
    """Проверка наличия пользователя в группе"""
    # Используем SISMEMBER вместо получения всей группы
    return bool(await redis.sismember(f"group:{group_id}:users", user_id))

@log_function_call
async def set_group_moderation(group_id: int, enabled: bool) -> None:
    """Включение/выключение модерации для группы"""
    await redis.hset(
        f"group:{group_id}",
        "is_moderation_enabled",
        int(enabled)
    )

@log_function_call
async def add_credits(user_id: int, amount: int) -> None:
    """Добавление кредитов пользователю"""
    await redis.hincrby(f"user:{user_id}", "credits", amount)

@log_function_call
async def deduct_credits(user_id: int, amount: int) -> bool:
    """Списание кредитов у пользователя. Возвращает True если списание успешно"""
    async with redis.pipeline() as pipe:
        while True:
            try:
                # Получаем текущий баланс
                await pipe.watch(f"user:{user_id}")
                current_credits = int(await redis.hget(f"user:{user_id}", "credits") or 0)

                if current_credits < amount:
                    return False

                await pipe.multi()
                await pipe.hincrby(f"user:{user_id}", "credits", -amount)
                await pipe.execute()
                return True
            except redis.WatchError:
                continue

@log_function_call
async def get_paying_admins(group_id: int) -> List[int]:
    """Получение списка админов с положительным балансом"""
    admin_ids = await redis.smembers(f"group:{group_id}:admins")
    paying_admins = []

    for admin_id in admin_ids:
        credits = int(await redis.hget(f"user:{admin_id}", "credits") or 0)
        if credits > 0:
            paying_admins.append(int(admin_id))

    return paying_admins

@log_function_call
async def get_user_groups(user_id: int) -> List[int]:
    """Получение списка групп, где пользователь является админом"""
    # Используем паттерн для поиска всех групп
    groups = []
    async for key in redis.scan_iter("group:*:admins"):
        if await redis.sismember(key, user_id):
            group_id = int(key.split(":")[1])
            groups.append(group_id)
    return groups

@log_function_call
async def get_user(user_id: int) -> Optional[User]:
    """Получение информации о пользователе"""
    user_data = await redis.hgetall(f"user:{user_id}")
    if not user_data:
        return None

    return User(
        user_id=user_id,
        username=user_data.get("username"),
        credits=int(user_data.get("credits", 0)),
        is_active=bool(int(user_data.get("is_active", 1))),
        created_at=datetime.fromisoformat(user_data["created_at"]),
        last_updated=datetime.fromisoformat(user_data["last_updated"])
    )

@log_function_call
async def update_group_admins(group_id: int, admin_ids: List[int]) -> None:
    """Обновление списка администраторов группы"""
    async with redis.pipeline() as pipe:
        # Удаляем старый список и добавляем новый атомарно
        await pipe.delete(f"group:{group_id}:admins")
        if admin_ids:
            await pipe.sadd(f"group:{group_id}:admins", *admin_ids)
        # Обновляем timestamp последнего обновления
        await pipe.hset(
            f"group:{group_id}",
            "last_updated",
            datetime.now().isoformat()
        )
        await pipe.execute()

# Добавляем константы цен
SKIP_PRICE = 1
APPROVE_PRICE = 5
DELETE_PRICE = 10

@log_function_call
async def deduct_credits_from_admins(group_id: int, amount: int) -> bool:
    """Списание кредитов у первого админа с достаточным балансом"""
    paying_admins = await get_paying_admins(group_id)

    for admin_id in paying_admins:
        if await deduct_credits(admin_id, amount):
            return True

    return False

@log_function_call
async def ensure_group_exists(group_id: int, admin_ids: List[int]) -> None:
    """Создание группы если она не существует"""
    exists = await redis.exists(f"group:{group_id}")
    if not exists:
        async with redis.pipeline() as pipe:
            # Сохраняем основные данные группы
            await pipe.hset(
                f"group:{group_id}",
                mapping={
                    "is_moderation_enabled": 1,  # Включаем модерацию по умолчанию
                    "created_at": datetime.now().isoformat(),
                    "last_updated": datetime.now().isoformat()
                }
            )
            # Сохраняем админов
            if admin_ids:
                await pipe.sadd(f"group:{group_id}:admins", *admin_ids)
            await pipe.execute()

@log_function_call
async def is_moderation_enabled(group_id: int) -> bool:
    """Проверка включена ли модерация в группе"""
    enabled = await redis.hget(f"group:{group_id}", "is_moderation_enabled")
    return bool(int(enabled or 0))
