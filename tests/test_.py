from unittest.mock import Mock
from main import handle_spam
import pytest
import asyncio


@pytest.mark.asyncio
@pytest.mark.skip
async def test_handle_spam():
    # Create mock objects for the dependencies
    mock_bot = Mock()
    mock_config = Mock()

    # Set up the necessary mock behavior
    mock_config.return_value = {
        "spam_control": {"delete_messages": True, "block_users": True}
    }
    mock_bot.delete_message.return_value = asyncio.sleep(
        0
    )  # Return a coroutine that returns None
    mock_bot.ban_chat_member.return_value = asyncio.sleep(
        0
    )  # Return a coroutine that returns None

    # Call the function you want to test
    message = {"message_id": 123, "text": "Spam message"}
    chat_id = 456
    user_id = 789
    await handle_spam(mock_bot, message, chat_id, user_id)

    # Add assertions to check the expected behavior
    mock_bot.delete_message.assert_called_once_with(chat_id, message["message_id"])
    mock_bot.ban_chat_member.assert_called_once_with(chat_id, user_id)
