import pytest
from unittest.mock import AsyncMock, patch
from aiogram.types import CallbackQuery, User, Message, Chat

from src.app.handlers.callback_handlers import handle_spam_ignore_callback


@pytest.mark.asyncio
async def test_handle_spam_ignore_callback_answer_error():
    """
    Test that handle_spam_ignore_callback continues execution even if callback.answer fails
    (e.g. due to query being too old), and that admin_id is correctly bound.
    """
    callback = AsyncMock(spec=CallbackQuery)
    callback.data = "mark_as_not_spam:1"
    callback.from_user = User(id=999, is_bot=False, first_name="Admin")
    callback.message = AsyncMock(spec=Message)
    callback.message.chat = Chat(id=456, type="supergroup")
    callback.message.message_id = 111
    callback.message.text = "Spam message content"

    callback.answer.side_effect = Exception("Query is too old")

    with (
        patch("src.app.handlers.callback_handlers.bot") as mock_bot,
        patch(
            "src.app.handlers.callback_handlers.confirm_pending_spam_example",
            new_callable=AsyncMock,
        ) as mock_confirm,
        patch(
            "src.app.handlers.callback_handlers.add_member",
            new_callable=AsyncMock,
        ),
    ):
        mock_confirm.return_value = {
            "chat_id": 456,
            "message_id": 100,
            "effective_user_id": 123,
        }
        mock_bot.edit_message_text = AsyncMock()
        mock_bot.unban_chat_member = AsyncMock()

        result = await handle_spam_ignore_callback(callback)

        assert result == "callback_marked_as_not_spam"
        mock_confirm.assert_called_once_with(1, 999)


@pytest.mark.asyncio
async def test_handle_spam_ignore_callback_confirm_raises():
    """
    Test that if confirm_pending_spam_example raises, handler returns error.
    """
    callback = AsyncMock(spec=CallbackQuery)
    callback.data = "mark_as_not_spam:1"
    callback.from_user = User(id=999, is_bot=False, first_name="Admin")
    callback.message = AsyncMock(spec=Message)

    with patch(
        "src.app.handlers.callback_handlers.confirm_pending_spam_example",
        new_callable=AsyncMock,
        side_effect=Exception("Network error"),
    ):
        result = await handle_spam_ignore_callback(callback)

        assert result == "callback_error_marking_not_spam"
