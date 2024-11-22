import json
from unittest.mock import MagicMock, patch

import pytest

from common.database.spam_examples import (
    SPAM_EXAMPLES_KEY,
    USER_SPAM_EXAMPLES_KEY,
    add_spam_example,
    get_spam_examples,
    remove_spam_example,
)


@pytest.fixture(autouse=True)
def mock_logger():
    with patch("common.database.spam_examples.get_yandex_logger") as mock:
        logger_mock = MagicMock()
        mock.return_value = logger_mock
        yield logger_mock


@pytest.fixture
def example_data():
    return {
        "text": "Buy cheap products!",
        "score": 90,
        "name": "Spammer",
        "bio": "Professional marketer",
    }


@pytest.fixture
def redis_mock():
    with patch("common.database.spam_examples.redis") as mock:
        yield mock


@pytest.mark.asyncio
async def test_get_spam_examples_common(redis_mock):
    # Setup mock data
    example = {"text": "spam text", "score": 80}
    redis_mock.lrange.return_value = [json.dumps(example)]

    # Get examples without admin_id
    result = await get_spam_examples()

    # Verify
    assert len(result) == 1
    assert result[0]["text"] == "spam text"
    assert result[0]["score"] == 80
    redis_mock.lrange.assert_called_once_with(SPAM_EXAMPLES_KEY, 0, -1)


@pytest.mark.asyncio
async def test_get_spam_examples_with_admin(redis_mock):
    # Setup mock data
    common_example = {"text": "common spam", "score": 80}
    user_example = {"text": "user spam", "score": 90}

    redis_mock.lrange.side_effect = [
        [json.dumps(common_example)],  # Common examples
        [json.dumps(user_example)],  # User examples
    ]

    # Get examples with admin_id
    admin_id = 12345
    result = await get_spam_examples(admin_id)

    # Verify
    assert len(result) == 2
    assert any(ex["text"] == "common spam" for ex in result)
    assert any(ex["text"] == "user spam" for ex in result)
    redis_mock.lrange.assert_any_call(SPAM_EXAMPLES_KEY, 0, -1)
    redis_mock.lrange.assert_any_call(f"{USER_SPAM_EXAMPLES_KEY}:{admin_id}", 0, -1)


@pytest.mark.asyncio
async def test_add_spam_example_common(redis_mock, example_data):
    # Add example without admin_id
    result = await add_spam_example(
        text=example_data["text"],
        score=example_data["score"],
        name=example_data["name"],
        bio=example_data["bio"],
    )

    # Verify
    assert result is True
    redis_mock.lpush.assert_called_once_with(
        SPAM_EXAMPLES_KEY, json.dumps(example_data)
    )


@pytest.mark.asyncio
async def test_add_spam_example_user_specific(redis_mock, example_data):
    admin_id = 12345

    # Add example with admin_id
    result = await add_spam_example(
        text=example_data["text"],
        score=example_data["score"],
        name=example_data["name"],
        bio=example_data["bio"],
        admin_id=admin_id,
    )

    # Verify
    assert result is True
    redis_mock.lpush.assert_called_once_with(
        f"{USER_SPAM_EXAMPLES_KEY}:{admin_id}", json.dumps(example_data)
    )


@pytest.mark.asyncio
async def test_add_spam_example_duplicate(redis_mock, example_data):
    # Setup existing example
    redis_mock.lrange.return_value = [json.dumps(example_data)]

    # Add duplicate example
    result = await add_spam_example(
        text=example_data["text"],
        score=95,  # Different score
        name=example_data["name"],
    )

    # Verify old example was removed and new one added
    assert result is True
    redis_mock.lrem.assert_called_once()
    redis_mock.lpush.assert_called_once()


@pytest.mark.asyncio
async def test_remove_spam_example(redis_mock, example_data):
    # Setup existing example
    redis_mock.lrange.return_value = [json.dumps(example_data)]

    # Remove example
    result = await remove_spam_example(example_data["text"])

    # Verify
    assert result is True
    redis_mock.lrem.assert_called_once_with(
        SPAM_EXAMPLES_KEY, 1, json.dumps(example_data)
    )


@pytest.mark.asyncio
async def test_remove_spam_example_not_found(redis_mock):
    # Setup empty redis
    redis_mock.lrange.return_value = []

    # Try to remove non-existent example
    result = await remove_spam_example("nonexistent")

    # Verify
    assert result is False
    redis_mock.lrem.assert_not_called()
