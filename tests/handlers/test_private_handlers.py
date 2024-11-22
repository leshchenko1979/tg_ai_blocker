from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram import types

from handlers.private_handlers import (
    OriginalMessageExtractionError,
    extract_original_message_info,
    handle_forwarded_message,
    handle_private_message,
    process_spam_example_callback,
)


@pytest.fixture(autouse=True)
def mock_logger():
    with patch("handlers.private_handlers.get_yandex_logger") as mock:
        logger_mock = MagicMock()
        mock.return_value = logger_mock
        yield logger_mock


@pytest.fixture
def user_mock():
    user = MagicMock()
    user.id = 123456789
    user.username = "testuser"
    user.first_name = "Test"
    user.full_name = "Test User"
    return user


@pytest.fixture
def private_message_mock(user_mock):
    message = MagicMock(spec=types.Message)
    message.text = "Test private message"
    message.from_user = user_mock
    message.chat = MagicMock()
    message.chat.type = "private"
    message.reply = AsyncMock()
    return message


@pytest.fixture
def forwarded_message_mock(user_mock):
    message = MagicMock(spec=types.Message)
    message.forward_from = MagicMock()
    message.forward_from.id = 987654321
    message.forward_from.full_name = "Forwarded User"
    message.text = "Forwarded message text"
    message.from_user = user_mock
    message.chat = MagicMock()
    message.chat.type = "private"
    message.forward_date = "2024-01-01 12:00:00"
    message.reply = AsyncMock()
    return message


@pytest.fixture
def callback_query_mock(user_mock):
    callback = MagicMock(spec=types.CallbackQuery)
    callback.id = "test_callback_id"
    callback.data = "spam_example:spam"
    callback.from_user = user_mock
    callback.message = MagicMock()
    callback.message.chat = MagicMock()
    callback.message.chat.id = 123456789
    callback.message.message_id = 1
    return callback


@pytest.mark.asyncio
async def test_handle_private_message(private_message_mock):
    with patch("handlers.private_handlers.save_message") as save_mock, patch(
        "handlers.private_handlers.get_message_history"
    ) as history_mock, patch(
        "handlers.private_handlers.get_openrouter_response"
    ) as llm_mock, patch(
        "handlers.private_handlers.get_spam_examples"
    ) as examples_mock, patch(
        "pathlib.Path.read_text"
    ) as read_mock:
        history_mock.return_value = [
            {"role": "user", "content": "Previous message"},
            {"role": "assistant", "content": "Previous response"},
        ]
        llm_mock.return_value = "Bot response"
        examples_mock.return_value = [
            {"text": "spam text", "score": 90, "name": "spammer"}
        ]
        read_mock.return_value = "PRD content"

        await handle_private_message(private_message_mock)

        save_mock.assert_any_call(123456789, "user", "Test private message")
        save_mock.assert_any_call(123456789, "assistant", "Bot response")
        llm_mock.assert_called_once()
        private_message_mock.reply.assert_awaited_once_with(
            "Bot response", parse_mode="markdown"
        )


@pytest.mark.asyncio
async def test_handle_forwarded_message(forwarded_message_mock):
    await handle_forwarded_message(forwarded_message_mock)

    forwarded_message_mock.reply.assert_awaited_once()
    call_args = forwarded_message_mock.reply.call_args
    assert "Добавить это сообщение в базу примеров?" in call_args[0]

    keyboard = call_args[1]["reply_markup"]
    buttons = keyboard.inline_keyboard[0]
    assert len(buttons) == 2
    assert buttons[0].text == "⚠️ Спам"
    assert buttons[1].text == "💚 Не спам"


@pytest.mark.asyncio
@pytest.mark.skip(reason="Failed to mock bot __call__ method")
async def test_process_spam_example_callback(callback_query_mock):
    with patch(
        "handlers.private_handlers.extract_original_message_info"
    ) as extract_mock, patch(
        "handlers.private_handlers.add_spam_example"
    ) as add_mock, patch(
        "handlers.private_handlers.remove_member_from_group"
    ) as remove_mock, patch(
        "handlers.private_handlers.bot"
    ) as bot_mock:
        # Setup mocks
        extract_mock.return_value = {
            "user_id": 987654321,
            "name": "Spammer Name",
            "bio": "Spammer Bio",
            "text": "Spam message",
        }

        # Setup async mocks
        add_mock.return_value = True
        remove_mock.return_value = None

        # Setup bot mock methods as coroutines
        async def answer_callback_query(*args, **kwargs):
            return True

        async def edit_message_text(*args, **kwargs):
            return True

        bot_mock.answer_callback_query = answer_callback_query
        bot_mock.edit_message_text = edit_message_text

        # Mock the bot instance itself as a coroutine
        async def bot_call(*args, **kwargs):
            return True

        bot_mock.__call__ = bot_call

        # Execute
        await process_spam_example_callback(callback_query_mock)

        # Verify spam example was added
        add_mock.assert_called_once_with(
            "Spam message",
            name="Spammer Name",
            bio="Spammer Bio",
            score=100,
            admin_id=123456789,
        )

        # Verify user was removed from group
        remove_mock.assert_called_once_with(member_id=987654321)


@pytest.mark.asyncio
async def test_extract_original_message_info():
    callback_message = MagicMock()
    callback_message.reply_to_message = MagicMock()
    callback_message.reply_to_message.forward_from = MagicMock()
    callback_message.reply_to_message.forward_from_chat = None
    callback_message.reply_to_message.forward_from.id = 987654321
    callback_message.reply_to_message.forward_from.full_name = "Original User"
    callback_message.reply_to_message.text = "Original message"

    with patch("handlers.private_handlers.bot.get_chat") as get_chat_mock:
        get_chat_mock.return_value = MagicMock(bio="User bio")

        result = await extract_original_message_info(callback_message)

        assert result["user_id"] == 987654321
        assert result["name"] == "Original User"
        assert result["bio"] == "User bio"
        assert result["text"] == "Original message"


@pytest.mark.asyncio
async def test_extract_original_message_info_channel_message():
    callback_message = MagicMock()
    callback_message.reply_to_message = MagicMock()
    callback_message.reply_to_message.forward_from_chat = MagicMock()

    with pytest.raises(OriginalMessageExtractionError) as exc_info:
        await extract_original_message_info(callback_message)

    assert (
        "Cannot extract meaningful message information from forwarded channel message"
        in str(exc_info.value)
    )


@pytest.mark.asyncio
async def test_handle_private_message_error(private_message_mock):
    with patch("handlers.private_handlers.save_message") as save_mock:
        save_mock.side_effect = Exception("Database error")

        with pytest.raises(Exception) as exc_info:
            await handle_private_message(private_message_mock)

        assert "Database error" in str(exc_info.value)
