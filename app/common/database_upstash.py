"""
Модуль для работы с базой данных Upstash
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel
from .dp import redis
from .bot import bot
from .yandex_logging import get_yandex_logger, log_function_call


logger = get_yandex_logger(__name__)


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

INITIAL_CREDITS = 100

# Добавляем константы цен
NEW_USER_PRICE = 1  # Стоимость обработки сообщения от нового пользователя
SKIP_PRICE = 0
APPROVE_PRICE = 0
DELETE_PRICE = 0

@log_function_call(logger)
async def save_user(user: User) -> None:
    """Сохранение пользователя в Redis"""
    await redis.hset(
        f"user:{user.user_id}",
        values={
            "username": user.username or "",
            "credits": user.credits,
            "is_active": int(user.is_active),
            "created_at": user.created_at.isoformat(),
            "last_updated": datetime.now().isoformat(),
        },
    )


@log_function_call(logger)
async def save_group(group: Group) -> None:
    """Сохранение группы в Redis"""
    # Сохраняем основные данные в hash
    await redis.hset(
        f"group:{group.group_id}",
        values={
            "is_moderation_enabled": int(group.is_moderation_enabled),
            "created_at": group.created_at.isoformat(),
            "last_updated": datetime.now().isoformat(),
        },
    )
    # Сохраняем admin_ids и unique_users в отдельных sets
    await redis.delete(f"group:{group.group_id}:admins")
    await redis.delete(f"group:{group.group_id}:users")
    if group.admin_ids:
        await redis.sadd(f"group:{group.group_id}:admins", *group.admin_ids)
    if group.unique_users:
        await redis.sadd(f"group:{group.group_id}:users", *group.unique_users)


@log_function_call(logger)
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
        last_updated=datetime.fromisoformat(group_data["last_updated"]),
    )


@log_function_call(logger)
async def add_unique_user(group_id: int, user_id: int) -> None:
    """Добавление уникального пользователя в группу"""
    await redis.sadd(f"group:{group_id}:users", user_id)


@log_function_call(logger)
async def is_user_in_group(group_id: int, user_id: int) -> bool:
    """Проверка наличия пользователя в группе"""
    # Используем SISMEMBER вместо получения всей группы
    return bool(await redis.sismember(f"group:{group_id}:users", user_id))


@log_function_call(logger)
async def set_group_moderation(group_id: int, enabled: bool) -> None:
    """Включение/выключение модерации для группы"""
    await redis.hset(
        f"group:{group_id}", values={"is_moderation_enabled": int(enabled)}
    )


@log_function_call(logger)
async def add_credits(user_id: int, amount: int) -> None:
    """Добавление кредитов пользователю и включение модерации в группах"""
    await redis.hincrby(f"user:{user_id}", "credits", amount)

    # Получаем все группы, где пользователь является админом
    user_groups = await get_user_groups(user_id)

    # Включаем модерацию в каждой группе
    for group_id in user_groups:
        await set_group_moderation(group_id, True)


@log_function_call(logger)
async def deduct_credits(user_id: int, amount: int) -> bool:
    """Списание кредитов у пользователя. Возвращает True если списание успешно"""
    try:
        # Получаем текущий баланс
        current_credits = int(await redis.hget(f"user:{user_id}", "credits") or 0)

        if current_credits < amount:
            return False

        await redis.hincrby(f"user:{user_id}", "credits", -amount)
        return True
    except Exception as e:
        logger.error(f"Ошибка при списании кредитов: {e}")
        raise


@log_function_call(logger)
async def update_group_admins(group_id: int, admin_ids: List[int]) -> None:
    """Обновление списка администраторов группы"""
    # Используем pipeline в стиле Upstash
    pipeline = redis.pipeline()

    pipeline.delete(f"group:{group_id}:admins")
    if admin_ids:
        pipeline.sadd(f"group:{group_id}:admins", *admin_ids)
    pipeline.hset(f"group:{group_id}", "last_updated", datetime.now().isoformat())
    await pipeline.exec()


@log_function_call(logger)
async def ensure_group_exists(group_id: int, admin_ids: List[int]) -> None:
    """Создание группы если она не существует"""
    exists = await redis.exists(f"group:{group_id}")
    if not exists:
        await redis.hset(
            f"group:{group_id}",
            values={
                "is_moderation_enabled": 1,
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
            },
        )
        if admin_ids:
            await redis.sadd(f"group:{group_id}:admins", *admin_ids)


@log_function_call(logger)
async def get_paying_admins(group_id: int) -> List[int]:
    """Получение списка админов с положительным балансом"""
    admin_ids = await redis.smembers(f"group:{group_id}:admins")
    paying_admins = []

    for admin_id in admin_ids:
        credits = int(await redis.hget(f"user:{admin_id}", "credits") or 0)
        if credits > 0:
            paying_admins.append(int(admin_id))

    return paying_admins


@log_function_call(logger)
async def get_user_groups(user_id: int) -> List[int]:
    """Получение списка групп, где пользователь является админом"""
    # Используем scan вместо scan_iter
    groups = []
    cursor = 0
    pattern = "group:*:admins"

    while True:
        cursor, keys = await redis.scan(cursor, match=pattern)
        for key in keys:
            if await redis.sismember(key, user_id):
                # Извлекаем group_id из ключа (формат: group:{id}:admins)
                group_id = int(key.split(":")[1])
                groups.append(group_id)

        if cursor == 0:  # Когда cursor возвращается в 0, сканирование завершено
            break

    return groups


@log_function_call(logger)
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
        last_updated=datetime.fromisoformat(user_data["last_updated"]),
    )




@log_function_call(logger)
async def deduct_credits_from_admins(group_id: int, amount: int) -> bool:
    """Списание кредитов у первого админа с достаточным балансом"""
    paying_admins = await get_paying_admins(group_id)

    for admin_id in paying_admins:
        if await deduct_credits(admin_id, amount):
            return True

    return False


@log_function_call(logger)
async def is_moderation_enabled(group_id: int) -> bool:
    """Проверка включена ли модерация в группе"""
    enabled = await redis.hget(f"group:{group_id}", "is_moderation_enabled")
    return bool(int(enabled or 0))


@log_function_call(logger)
async def initialize_new_user(user_id: int) -> bool:
    """
    Инициализирует нового пользователя с начальными кредитами.

    Args:
        user_id: ID пользователя

    Returns:
        bool: True если пользователь был создан, False если уже существует
    """
    exists = await redis.exists(f"user:{user_id}")
    if not exists:
        await redis.hset(
            f"user:{user_id}",
            values={
                "credits": INITIAL_CREDITS,
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
            },
        )
        return True
    return False

@log_function_call(logger)
async def get_user_credits(user_id: int) -> int:
    """
    Получает количество кредитов пользователя.
    Если пользователь новый - инициализирует его с начальным балансом.

    Args:
        user_id: ID пользователя

    Returns:
        int: Количество кредитов
    """
    # Проверяем существование пользователя
    exists = await redis.exists(f"user:{user_id}")

    if not exists:
        # Инициализируем нового пользователя
        await redis.hset(
            f"user:{user_id}",
            values={
                "credits": INITIAL_CREDITS,
                "created_at": datetime.now().isoformat(),
            },
        )
        return INITIAL_CREDITS

    credits = await redis.hget(f"user:{user_id}", "credits")
    return int(credits or 0)


async def get_user_admin_groups(user_id: int):
    """
    Возвращает список групп, где пользователь является админом

    Args:
        user_id: ID пользователя

    Returns:
        list: Список словарей с информацией о группах (id, title)
    """
    groups = []
    cursor = 0

    while True:
        cursor, keys = await redis.scan(cursor, match="group:*")
        for key in keys:
            if (
                key.count(":") == 1
            ):  # Пропускаем ключи с дополнительными частями (group:id:admins)
                group_id = int(key.split(":")[1])

                # Проверяем, является ли пользователь админом
                is_admin = await redis.sismember(f"group:{group_id}:admins", user_id)

                if is_admin:
                    # Получаем название группы через API Telegram
                    try:
                        chat = await bot.get_chat(group_id)
                        groups.append({"id": group_id, "title": chat.title})
                    except Exception as e:
                        logger.error(f"Error getting chat {group_id}: {e}")
                        continue
        if cursor == 0:
            break

    return groups
