import json
from typing import Any, Dict, List, Optional

from ..yandex_logging import get_yandex_logger, log_function_call
from .redis_connection import redis

logger = get_yandex_logger(__name__)

SPAM_EXAMPLES_KEY = "spam_examples"
USER_SPAM_EXAMPLES_KEY = "user_spam_examples"


@log_function_call(logger)
async def get_spam_examples(user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Get spam examples from Redis, optionally filtered by user_id"""
    try:
        # Get common spam examples
        common_examples = await redis.lrange(SPAM_EXAMPLES_KEY, 0, -1)

        # Get user-specific spam examples if user_id is provided
        user_examples = []
        if user_id is not None:
            user_examples = await redis.lrange(
                f"{USER_SPAM_EXAMPLES_KEY}:{user_id}", 0, -1
            )

        # Combine and parse examples
        all_examples = common_examples + user_examples
        return [json.loads(example) for example in all_examples]
    except Exception as e:
        logger.error(f"Error getting spam examples: {e}")
        return []


@log_function_call(logger)
async def add_spam_example(
    text: str,
    score: int,
    name: Optional[str] = None,
    bio: Optional[str] = None,
    user_id: Optional[int] = None,
) -> bool:
    """Add a new spam example to Redis"""
    try:
        # First find and delete existing entry with the same name and text
        examples = await get_spam_examples(user_id)
        for example in examples:
            if example["text"] == text and example.get("name") == name:
                if user_id is None:
                    await redis.lrem(SPAM_EXAMPLES_KEY, 1, json.dumps(example))
                else:
                    await redis.lrem(
                        f"{USER_SPAM_EXAMPLES_KEY}:{user_id}", 1, json.dumps(example)
                    )

        example = {"text": text, "score": score, "name": name, "bio": bio}
        # Remove None values
        example = {k: v for k, v in example.items() if v is not None}

        # Add to appropriate list based on user_id
        if user_id is None:
            await redis.lpush(SPAM_EXAMPLES_KEY, json.dumps(example))
        else:
            await redis.lpush(
                f"{USER_SPAM_EXAMPLES_KEY}:{user_id}", json.dumps(example)
            )

        return True
    except Exception as e:
        logger.error(f"Error adding spam example: {e}")
        return False


@log_function_call(logger)
async def remove_spam_example(text: str) -> bool:
    """Remove a spam example from Redis by its text"""
    try:
        examples = await get_spam_examples()
        for example in examples:
            if example["text"] == text:
                await redis.lrem(SPAM_EXAMPLES_KEY, 1, json.dumps(example))
                return True
        return False
    except Exception as e:
        logger.error(f"Error removing spam example: {e}")
        return False


@log_function_call(logger)
async def initialize_spam_examples(examples: List[Dict[str, Any]]) -> bool:
    """Initialize spam examples in Redis from a list"""
    try:
        # Clear existing examples
        await redis.delete(SPAM_EXAMPLES_KEY)

        # Add new examples
        if examples:
            pipeline = redis.pipeline()
            for example in examples:
                # Ensure we only store non-None values
                example = {k: v for k, v in example.items() if v is not None}
                pipeline.rpush(SPAM_EXAMPLES_KEY, json.dumps(example))
            await pipeline.execute()
        return True
    except Exception as e:
        logger.error(f"Error initializing spam examples: {e}")
        return False
