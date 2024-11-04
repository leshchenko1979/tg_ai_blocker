from aiogram import Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from .database import redis

dp = Dispatcher(storage=RedisStorage(redis=redis))
