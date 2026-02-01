import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.types import CallbackQuery, User, Message, Chat

from src.app.handlers.callback_handlers import handle_spam_ignore_callback


@pytest.mark.asyncio
async def test_handle_spam_ignore_callback_answer_error():
    """
    Test that handle_spam_ignore_callback continues execution even if callback.answer fails
    (e.g. due to query being too old), and that admin_id is correctly bound.
    """
    # Mock callback
    callback = AsyncMock(spec=CallbackQuery)
    callback.data = "mark_as_not_spam:123:456"
    callback.from_user = User(id=999, is_bot=False, first_name="Admin")
    callback.message = AsyncMock(spec=Message)
    callback.message.chat = Chat(id=456, type="supergroup")
    callback.message.message_id = 111
    callback.message.text = "Spam message content"

    # Mock answer raising exception
    callback.answer.side_effect = Exception("Query is too old")

    # Mocks
    with (
        patch("src.app.handlers.callback_handlers.bot") as mock_bot,
        patch("src.app.handlers.callback_handlers.add_spam_example") as mock_add_spam,
        patch("src.app.handlers.callback_handlers.add_member") as mock_add_member,
        patch(
            "src.app.handlers.callback_handlers.collect_user_context",
            new_callable=AsyncMock,
        ) as mock_collect,
    ):
        # Setup mocks
        mock_bot.get_chat = AsyncMock(
            return_value=MagicMock(username="spammer", full_name="Spammer", bio=None)
        )
        mock_bot.edit_message_text = AsyncMock()
        mock_bot.unban_chat_member = AsyncMock()
        # Mock UserContext return
        from src.app.spam.context_types import UserContext, ContextResult, ContextStatus

        mock_collect.return_value = UserContext(
            stories=ContextResult(status=ContextStatus.EMPTY),
            linked_channel=ContextResult(status=ContextStatus.EMPTY),
            account_info=ContextResult(status=ContextStatus.EMPTY),
        )

        # Run handler
        result = await handle_spam_ignore_callback(callback)

        # Verify result
        assert result == "callback_marked_as_not_spam"

        # Verify execution proceeded despite callback.answer error
        mock_add_spam.assert_called_once()


@pytest.mark.asyncio
async def test_handle_spam_ignore_callback_get_chat_error():
    """
    Test that if an error occurs (e.g. in bot.get_chat) before the logic completes,
    admin_id is still bound for error tracking.
    """
    # Mock callback
    callback = AsyncMock(spec=CallbackQuery)
    callback.data = "mark_as_not_spam:123:456"
    callback.from_user = User(id=999, is_bot=False, first_name="Admin")
    callback.message = AsyncMock(spec=Message)

    # Mocks
    with (
        patch("src.app.handlers.callback_handlers.bot") as mock_bot,
    ):
        # Setup mocks to raise error
        mock_bot.get_chat = AsyncMock(side_effect=Exception("Network error"))

        # Run handler
        result = await handle_spam_ignore_callback(callback)

        # Verify result is error
        assert result == "callback_error_marking_not_spam"
