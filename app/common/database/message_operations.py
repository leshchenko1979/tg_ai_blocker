import json
from datetime import datetime
from typing import List

from ..yandex_logging import get_yandex_logger, log_function_call
from .redis_connection import redis

logger = get_yandex_logger(__name__)

# Constants
MESSAGE_HISTORY_SIZE = 30  # Number of messages to keep in history
MESSAGE_TTL = 60 * 60 * 24  # 24 hours in seconds


@log_function_call(logger)
async def save_message(admin_id: int, role: str, content: str) -> None:
    """Save a message to the admin's conversation history"""
    history_key = f"message_history:{admin_id}"

    pipeline = redis.pipeline()
    pipeline.lpush(
        history_key,
        json.dumps(
            {
                "role": role,
                "content": content,
                "timestamp": datetime.now().isoformat(),
            }
        ),
    )
    pipeline.ltrim(history_key, 0, MESSAGE_HISTORY_SIZE - 1)
    pipeline.expire(history_key, MESSAGE_TTL)
    await pipeline.execute()


@log_function_call(logger)
async def get_message_history(admin_id: int) -> List[dict]:
    """Retrieve admin's conversation history"""
    history_key = f"message_history:{admin_id}"
    raw_messages = await redis.lrange(history_key, 0, -1)

    messages = []
    for raw_message in raw_messages:
        try:
            message_data = json.loads(raw_message)
            messages.append(
                {"role": message_data["role"], "content": message_data["content"]}
            )
        except Exception as e:
            logger.error(f"Error parsing message history: {e}")
            continue

    # Return messages in chronological order
    return list(reversed(messages))


@log_function_call(logger)
async def clear_message_history(admin_id: int) -> None:
    """Clear admin's conversation history"""
    history_key = f"message_history:{admin_id}"
    await redis.delete(history_key)
