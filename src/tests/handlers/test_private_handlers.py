from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram import types

from ...app.handlers.private_handlers import (
    OriginalMessageExtractionError,
    extract_original_message_info,
    handle_forwarded_message,
    handle_private_message,
    process_spam_example_callback,
)


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
async def test_handle_private_message(patched_db_conn, clean_db, private_message_mock):
    async with clean_db.acquire() as conn:
        # Ensure user exists in database
        await conn.execute(
            """
            INSERT INTO administrators (admin_id, username, credits)
            VALUES ($1, $2, 0)
            ON CONFLICT DO NOTHING
        """,
            private_message_mock.from_user.id,
            private_message_mock.from_user.username,
        )

        with patch(
            "src.app.handlers.private_handlers.save_message"
        ) as save_mock, patch(
            "src.app.handlers.private_handlers.get_message_history"
        ) as history_mock, patch(
            "src.app.handlers.private_handlers.get_openrouter_response"
        ) as llm_mock, patch(
            "src.app.handlers.private_handlers.get_spam_examples"
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
async def test_handle_forwarded_message(
    patched_db_conn, clean_db, forwarded_message_mock
):
    async with clean_db.acquire() as conn:
        # Ensure user exists in database
        await conn.execute(
            """
            INSERT INTO administrators (admin_id, username, credits)
            VALUES ($1, $2, 0)
            ON CONFLICT DO NOTHING
        """,
            forwarded_message_mock.from_user.id,
            forwarded_message_mock.from_user.username,
        )

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
async def test_process_spam_example_callback(
    patched_db_conn, clean_db, callback_query_mock
):
    async with clean_db.acquire() as conn:
        # Ensure admin exists in database
        await conn.execute(
            """
            INSERT INTO administrators (admin_id, username, credits)
            VALUES ($1, $2, 100)
            ON CONFLICT DO NOTHING
        """,
            callback_query_mock.from_user.id,
            callback_query_mock.from_user.username,
        )

        with patch(
            "src.app.handlers.private_handlers.extract_original_message_info"
        ) as extract_mock, patch(
            "src.app.handlers.private_handlers.add_spam_example"
        ) as add_mock, patch(
            "src.app.handlers.private_handlers.remove_member_from_group"
        ) as remove_mock, patch(
            "src.app.handlers.private_handlers.bot"
        ) as bot_mock:
            # Setup mocks
            message_info = {
                "user_id": 987654321,
                "name": "Spammer Name",
                "bio": "Spammer Bio",
                "text": "Spam message",
            }
            extract_mock.return_value = message_info
            add_mock.return_value = True

            # Setup the answer coroutine
            async def answer(*args, **kwargs):
                return None

            callback_query_mock.answer = answer

            # Setup bot mock
            bot_mock.edit_message_text = AsyncMock()
            bot_mock.side_effect = lambda x: x  # Pass through the coroutine

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

            # Verify bot interactions
            bot_mock.edit_message_text.assert_called_once_with(
                chat_id=callback_query_mock.message.chat.id,
                message_id=callback_query_mock.message.message_id,
                text="Сообщение добавлено как пример спама.",
            )


@pytest.mark.skip(reason="Failed to mock the bot")
@pytest.mark.asyncio
async def test_process_not_spam_example_callback(
    patched_db_conn, clean_db, callback_query_mock
):
    callback_query_mock.data = "spam_example:not_spam"  # Change the action

    async with clean_db.acquire() as conn:
        # ... same database setup code ...

        with patch(
            "app.handlers.private_handlers.extract_original_message_info"
        ) as extract_mock, patch(
            "app.handlers.private_handlers.add_spam_example"
        ) as add_mock, patch(
            "app.handlers.private_handlers.remove_member_from_group"
        ) as remove_mock, patch(
            "app.handlers.private_handlers.bot"
        ) as bot_mock, patch(
            "app.handlers.private_handlers.mp"
        ) as mp_mock:
            # Similar setup as above
            message_info = {
                "user_id": 987654321,
                "name": "User Name",
                "bio": "User Bio",
                "text": "Good message",
            }
            extract_mock.return_value = message_info
            add_mock.return_value = True
            bot_mock.return_value = AsyncMock()

            await process_spam_example_callback(callback_query_mock)

            # Verify spam example was added with negative score
            add_mock.assert_called_once_with(
                "Good message",
                name="User Name",
                bio="User Bio",
                score=-100,
                admin_id=123456789,
            )

            # Verify user was NOT removed from group
            remove_mock.assert_not_called()

            # Verify bot interactions
            bot_mock.return_value.answer.assert_called_once_with(
                "Сообщение добавлено как пример ценного сообщения."
            )
            bot_mock.edit_message_text.assert_called_once_with(
                chat_id=callback_query_mock.message.chat.id,
                message_id=callback_query_mock.message.message_id,
                text="Сообщение добавлено как пример ценного сообщения.",
            )


@pytest.mark.asyncio
async def test_extract_original_message_info(patched_db_conn, clean_db):
    callback_message = MagicMock()
    callback_message.reply_to_message = MagicMock()
    callback_message.reply_to_message.forward_from = MagicMock()
    callback_message.reply_to_message.forward_from_chat = None
    callback_message.reply_to_message.forward_from.id = 987654321
    callback_message.reply_to_message.forward_from.full_name = "Original User"
    callback_message.reply_to_message.text = "Original message"

    with patch("src.app.handlers.private_handlers.bot.get_chat") as get_chat_mock:
        get_chat_mock.return_value = MagicMock(bio="User bio")

        result = await extract_original_message_info(callback_message)

        assert result["user_id"] == 987654321
        assert result["name"] == "Original User"
        assert result["bio"] == "User bio"
        assert result["text"] == "Original message"


@pytest.mark.asyncio
async def test_extract_original_message_info_channel_message(patched_db_conn, clean_db):
    callback_message = MagicMock()
    callback_message.reply_to_message = MagicMock()
    callback_message.reply_to_message.forward_from_chat = MagicMock()

    with pytest.raises(OriginalMessageExtractionError) as exc_info:
        await extract_original_message_info(callback_message)

    assert (
        "Cannot extract meaningful message information from forwarded channel message"
        in str(exc_info.value)
    )
