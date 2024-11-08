import os
from datetime import datetime
from typing import Optional, List, Union, Dict, Any

from pydantic import BaseModel, Field, validator
from redis.asyncio import Redis
from redis.exceptions import RedisError

from .bot import bot
from .yandex_logging import get_yandex_logger, log_function_call


logger = get_yandex_logger(__name__)

class RedisConnection:
    """Manages Redis connection with enhanced type handling"""
    def __init__(self):
        self._redis = Redis(
            host=os.getenv("REDIS_HOST"),
            password=os.getenv("REDIS_PASSWORD")
        )

    async def safe_hset(self, key: str, mapping: Dict[str, Union[int, str, float]]):
        """Safely set hash values with type conversion"""
        try:
            # Convert all values to strings for consistent storage
            safe_mapping = {
                str(k): str(v) for k, v in mapping.items()
            }
            return await self._redis.hset(key, mapping=safe_mapping)
        except RedisError as e:
            logger.error(f"Redis HSET error: {e}")
            raise

    async def safe_sadd(self, key: str, *values):
        """Safely add to set with type conversion"""
        try:
            # Convert all values to strings
            safe_values = [str(v) for v in values]
            return await self._redis.sadd(key, *safe_values)
        except RedisError as e:
            logger.error(f"Redis SADD error: {e}")
            raise

    @property
    def redis(self):
        return self._redis

redis_conn = RedisConnection()
redis = redis_conn.redis

class User(BaseModel):
    """Enhanced User model with validation"""
    user_id: int
    username: Optional[str] = None
    credits: int = Field(default=0, ge=0)
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.now)
    last_updated: datetime = Field(default_factory=datetime.now)

    @validator('credits')
    def validate_credits(cls, v):
        if v < 0:
            raise ValueError("Credits cannot be negative")
        return v

class Group(BaseModel):
    """Enhanced Group model with validation"""
    group_id: int
    admin_ids: List[int]
    is_moderation_enabled: bool = True
    unique_users: List[int] = []
    created_at: datetime = Field(default_factory=datetime.now)
    last_updated: datetime = Field(default_factory=datetime.now)

INITIAL_CREDITS = 100

# Добавляем константы цен
SKIP_PRICE = 0
APPROVE_PRICE = 1
DELETE_PRICE = 1

@log_function_call(logger)
async def save_user(user: User) -> None:
    """Сохранение пользователя в Redis с улучшенной типизацией"""
    await redis_conn.safe_hset(
        f"user:{user.user_id}",
        {
            "username": user.username or "",
            "credits": user.credits,
            "is_active": int(user.is_active),
            "created_at": user.created_at.isoformat(),
            "last_updated": datetime.now().isoformat(),
        }
    )

@log_function_call(logger)
async def save_group(group: Group) -> None:
    """Сохранение группы в Redis с улучшенной типизацией"""
    pipeline = redis.pipeline()

    # Сохраняем основные данные в hash
    pipeline.hset(
        f"group:{group.group_id}",
        mapping={
            "is_moderation_enabled": int(group.is_moderation_enabled),
            "created_at": group.created_at.isoformat(),
            "last_updated": datetime.now().isoformat(),
        }
    )

    # Сохраняем admin_ids и unique_users в отдельных sets
    pipeline.delete(f"group:{group.group_id}:admins")
    pipeline.delete(f"group:{group.group_id}:users")

    if group.admin_ids:
        await redis_conn.safe_sadd(f"group:{group.group_id}:admins", *group.admin_ids)

    if group.unique_users:
        await redis_conn.safe_sadd(f"group:{group.group_id}:users", *group.unique_users)

    await pipeline.exec()

# Остальные функции остаются прежними, с добавлением безопасного преобразования типов
# (Полный код функций будет таким же, как в предыдущей версии,
# но с использованием redis_conn.safe_hset() и redis_conn.safe_sadd())

# Пример безопасного преобразования в других функциях:
@log_function_call(logger)
async def get_user_credits(user_id: int) -> int:
    """Получает количество кредитов пользователя с безопасным преобразованием"""
    try:
        credits_raw = await redis.hget(f"user:{user_id}", "credits")
        return int(credits_raw.decode()) if credits_raw else INITIAL_CREDITS
    except (TypeError, ValueError) as e:
        logger.error(f"Error getting user credits: {e}")
        return INITIAL_CREDITS

# Остальной код остается прежним
