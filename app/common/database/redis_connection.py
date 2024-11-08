import os

from redis.asyncio import Redis

from ..yandex_logging import get_yandex_logger

logger = get_yandex_logger(__name__)

redis = Redis(
    host=os.getenv("REDIS_HOST"),
    password=os.getenv("REDIS_PASSWORD"),
    decode_responses=True,
)
