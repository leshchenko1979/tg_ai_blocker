import os

from aiogram import Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from upstash_redis.asyncio.client import Redis


redis = Redis(
    url=os.getenv("REDIS_URL"), token=os.getenv("REDIS_TOKEN"), allow_telemetry=False
)

dp = Dispatcher(storage=RedisStorage(redis=redis))
