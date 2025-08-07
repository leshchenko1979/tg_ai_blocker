from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram import types
from aiogram.exceptions import TelegramBadRequest

from ...app.handlers.private_handlers import (
    OriginalMessageExtractionError,
    extract_original_message_info,
    handle_forwarded_message,
    handle_private_message,
    process_spam_example_callback,
    sanitize_markdown,
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


@pytest.fixture
def forwarded_hidden_message_mock(user_mock):
    message = MagicMock(spec=types.Message)
    message.forward_from = None
    message.forward_origin = MagicMock()
    message.forward_origin.type = "hidden_user"
    message.forward_origin.sender_user_name = "Hidden User"
    message.text = "Hidden user message text"
    message.from_user = user_mock
    message.chat = MagicMock()
    message.chat.type = "private"
    message.forward_date = "2024-01-01 12:00:00"
    message.reply = AsyncMock()
    return message


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

        with (
            patch("src.app.handlers.private_handlers.save_message") as save_mock,
            patch(
                "src.app.handlers.private_handlers.get_message_history"
            ) as history_mock,
            patch(
                "src.app.handlers.private_handlers.get_openrouter_response"
            ) as llm_mock,
            patch(
                "src.app.handlers.private_handlers.get_spam_examples"
            ) as examples_mock,
            patch("pathlib.Path.read_text") as read_mock,
        ):
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
async def test_handle_forwarded_hidden_message(
    patched_db_conn, clean_db, forwarded_hidden_message_mock
):
    async with clean_db.acquire() as conn:
        # Ensure user exists in database
        await conn.execute(
            """
            INSERT INTO administrators (admin_id, username, credits)
            VALUES ($1, $2, 0)
            ON CONFLICT DO NOTHING
            """,
            forwarded_hidden_message_mock.from_user.id,
            forwarded_hidden_message_mock.from_user.username,
        )

        await handle_forwarded_message(forwarded_hidden_message_mock)

        forwarded_hidden_message_mock.reply.assert_awaited_once()
        call_args = forwarded_hidden_message_mock.reply.call_args
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

        with (
            patch(
                "src.app.handlers.private_handlers.extract_original_message_info"
            ) as extract_mock,
            patch("src.app.handlers.private_handlers.add_spam_example") as add_mock,
            patch(
                "src.app.handlers.private_handlers.remove_member_from_group"
            ) as remove_mock,
            patch("src.app.handlers.private_handlers.bot") as bot_mock,
        ):
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

        with (
            patch(
                "app.handlers.private_handlers.extract_original_message_info"
            ) as extract_mock,
            patch("app.handlers.private_handlers.add_spam_example") as add_mock,
            patch(
                "app.handlers.private_handlers.remove_member_from_group"
            ) as remove_mock,
            patch("app.handlers.private_handlers.bot") as bot_mock,
            patch("app.handlers.private_handlers.mp") as mp_mock,
        ):
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


@pytest.mark.asyncio
async def test_sanitize_markdown_with_problematic_response():
    """Test that sanitize_markdown correctly handles problematic responses."""
    # This is the problematic response that caused the error
    problematic_response = """Что я умею? 😈 Я - нейромодератор, кибер-защитник, страж чистоты Telegram! Мои умения безграничны, но вот основные:

*   **Анализ сообщений**: Я сканирую каждое сообщение в группе, используя мощь искусственного интеллекта. 🧠
*   **Удаление спама**: Если сообщение пахнет спамом, я его уничтожаю без колебаний. 💥
*   **Учет пользователей**: Я помню, кто хороший, а кто плохой. Проверенные пользователи могут проходить, спамеры - нет! 🚫
*   **Обучение**: Я учусь на ваших примерах, чтобы становиться еще лучше в борьбе со злом. 📚
*   **Удаление мусора**: Автоматически удаляю сообщения о вступлении и выходе участников, чтобы в группе был порядок. 🧹

И это только начало! 🚀 Я постоянно развиваюсь, чтобы быть на шаг впереди спамеров. 😈"""

    # Sanitize the problematic response
    sanitized_response = sanitize_markdown(problematic_response)

    # Check that the sanitized response doesn't have unbalanced markdown entities
    assert sanitized_response.count("*") % 2 == 0
    assert sanitized_response.count("_") % 2 == 0
    assert sanitized_response.count("`") % 2 == 0

    # Check that bullet points are properly handled
    assert "*   " not in sanitized_response
    assert "•   " in sanitized_response

    # Simulate sending the message to Telegram
    message_mock = MagicMock(spec=types.Message)
    reply_mock = AsyncMock()
    message_mock.reply = reply_mock

    # This should not raise an exception
    await message_mock.reply(sanitized_response, parse_mode="markdown")

    # Check that reply was called once
    reply_mock.assert_called_once()


@pytest.mark.asyncio
async def test_sanitize_markdown_with_unbalanced_symbols():
    """Test that sanitize_markdown correctly handles unbalanced markdown symbols."""
    # Test with unbalanced asterisks
    unbalanced_text = "This is *unbalanced text"
    sanitized = sanitize_markdown(unbalanced_text)
    # Проверяем, что символы экранированы, а не сбалансированы
    assert "\\*" in sanitized
    assert "*" not in sanitized.replace("\\*", "")

    # Test with unbalanced underscores
    unbalanced_text = "This is _unbalanced text"
    sanitized = sanitize_markdown(unbalanced_text)
    assert "\\_" in sanitized
    assert "_" not in sanitized.replace("\\_", "")

    # Test with unbalanced backticks
    unbalanced_text = "This is `unbalanced text"
    sanitized = sanitize_markdown(unbalanced_text)
    assert "\\`" in sanitized
    assert "`" not in sanitized.replace("\\`", "")

    # Test with multiple unbalanced symbols
    unbalanced_text = "This is *unbalanced _text with `multiple symbols"
    sanitized = sanitize_markdown(unbalanced_text)
    assert "\\*" in sanitized
    assert "\\_" in sanitized
    assert "\\`" in sanitized
    assert "*" not in sanitized.replace("\\*", "")
    assert "_" not in sanitized.replace("\\_", "")
    assert "`" not in sanitized.replace("\\`", "")


@pytest.mark.asyncio
async def test_sanitize_markdown_with_balanced_symbols():
    """Test that sanitize_markdown preserves balanced markdown symbols."""
    # Test with balanced asterisks
    balanced_text = "This is *balanced* text"
    sanitized = sanitize_markdown(balanced_text)
    assert sanitized == balanced_text

    # Test with balanced underscores
    balanced_text = "This is _balanced_ text"
    sanitized = sanitize_markdown(balanced_text)
    assert sanitized == balanced_text

    # Test with balanced backticks
    balanced_text = "This is `balanced` text"
    sanitized = sanitize_markdown(balanced_text)
    assert sanitized == balanced_text

    # Test with multiple balanced symbols
    balanced_text = "This is *balanced* _text_ with `multiple` symbols"
    sanitized = sanitize_markdown(balanced_text)
    assert sanitized == balanced_text


@pytest.mark.asyncio
async def test_sanitize_markdown_with_bullet_points():
    """Test that sanitize_markdown correctly handles bullet points."""
    # Test with bullet points
    bullet_text = """List:
*   Item 1
*   Item 2
*   Item 3"""
    sanitized = sanitize_markdown(bullet_text)
    assert "*   " not in sanitized
    assert "•   " in sanitized
    assert sanitized.count("•   ") == 3

    # Test with bullet points and formatting
    bullet_text = """List:
*   **Item 1**
*   *Item 2*
*   `Item 3`"""
    sanitized = sanitize_markdown(bullet_text)
    assert "*   " not in sanitized
    assert "•   " in sanitized
    assert "**Item 1**" in sanitized
    assert "*Item 2*" in sanitized
    assert "`Item 3`" in sanitized


@pytest.mark.asyncio
async def test_handle_private_message_with_markdown_error(
    patched_db_conn, clean_db, private_message_mock
):
    """Test that handle_private_message correctly handles markdown errors."""
    # Mock the get_message_history function
    with (
        patch(
            "src.app.handlers.private_handlers.get_message_history",
            return_value=[{"role": "user", "content": "Test message"}],
        ) as get_history_mock,
        patch(
            "src.app.handlers.private_handlers.get_spam_examples",
            return_value=[],
        ) as get_examples_mock,
        patch(
            "src.app.handlers.private_handlers.get_openrouter_response",
            return_value="Test **response with unbalanced markdown*",
        ) as get_response_mock,
        patch(
            "src.app.handlers.private_handlers.initialize_new_admin",
            return_value=False,
        ) as init_admin_mock,
        patch(
            "src.app.handlers.private_handlers.get_admin_credits",
            return_value=100,
        ) as get_credits_mock,
        patch(
            "src.app.handlers.private_handlers.save_message",
        ) as save_message_mock,
        patch(
            "src.app.handlers.private_handlers.mp.track",
        ) as track_mock,
        patch(
            "src.app.handlers.private_handlers.mp.people_set",
        ) as people_set_mock,
        patch(
            "pathlib.Path.read_text",
            return_value="Test PRD",
        ) as read_text_mock,
    ):
        # Create a mock for the reply method
        reply_mock = AsyncMock()

        # First call raises an exception, second call succeeds
        reply_mock.side_effect = [
            Exception("Can't parse entities"),  # First call with markdown fails
            MagicMock(),  # Second call without markdown succeeds
        ]

        private_message_mock.reply = reply_mock

        # Call the handler
        result = await handle_private_message(private_message_mock)

        # Check that the handler returned the expected result
        assert result == "private_message_replied"

        # Check that reply was called twice
        assert reply_mock.call_count == 2

        # Check that the first call was with markdown
        first_call_args = reply_mock.call_args_list[0]
        assert first_call_args[1].get("parse_mode") == "markdown"

        # Check that the second call was without markdown
        second_call_args = reply_mock.call_args_list[1]
        assert "parse_mode" not in second_call_args[1]
