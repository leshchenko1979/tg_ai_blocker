import json
from datetime import datetime
from typing import List

from ..yandex_logging import get_yandex_logger, log_function_call
from .models import Message
from .redis_connection import redis

logger = get_yandex_logger(__name__)

# Constants
MESSAGE_HISTORY_SIZE = 30  # Number of messages to keep in history
MESSAGE_TTL = 60 * 60 * 24  # 24 hours in seconds


@log_function_call(logger)
async def save_message(user_id: int, role: str, content: str) -> None:
    """Save a message to the user's conversation history"""

    message = Message(
        message_id=f"{user_id}:{datetime.now().timestamp()}",
        user_id=user_id,
        role=role,
        content=content,
    )

    # Key for user's message history
    history_key = f"message_history:{user_id}"

    # Pipe commands to Redis
    pipeline = redis.pipeline()

    # Add message to the list, keeping only recent messages
    pipeline.lpush(
        history_key,
        json.dumps(
            {
                "message_id": message.message_id,
                "role": message.role,
                "content": message.content,
                "timestamp": message.timestamp.isoformat(),
            }
        ),
    )

    # Trim to keep only recent messages
    pipeline.ltrim(history_key, 0, MESSAGE_HISTORY_SIZE - 1)

    # Set TTL for the history
    pipeline.expire(history_key, MESSAGE_TTL)

    # Execute the pipeline
    await pipeline.execute()


@log_function_call(logger)
async def get_message_history(user_id: int) -> List[dict]:
    """Retrieve user's conversation history"""
    history_key = f"message_history:{user_id}"
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
async def clear_message_history(user_id: int) -> None:
    """Clear user's conversation history"""
    history_key = f"message_history:{user_id}"
    await redis.delete(history_key)
