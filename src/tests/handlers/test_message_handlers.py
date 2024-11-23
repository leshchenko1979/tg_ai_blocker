from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.handlers.message_handlers import (
    handle_moderated_message,
    handle_spam,
    try_deduct_credits,
)


@pytest.fixture(autouse=True)
def mock_logger():
    with patch("app.handlers.message_handlers.get_yandex_logger") as mock:
        logger_mock = MagicMock()
        mock.return_value = logger_mock
        yield logger_mock


@pytest.fixture(autouse=True)
def mock_bot():
    with patch("app.handlers.message_handlers.bot") as mock:
        mock.get_chat = AsyncMock()
        mock.get_chat.return_value = MagicMock(title="Test Group")

        mock.get_chat_administrators = AsyncMock()
        admin = MagicMock()
        admin.user.id = 111111
        admin.user.is_bot = False
        mock.get_chat_administrators.return_value = [admin]

        mock.send_message = AsyncMock()
        mock.delete_message = AsyncMock()
        yield mock


@pytest.fixture
def user_mock():
    user = MagicMock()
    user.id = 123456789
    user.username = "testuser"
    user.first_name = "Test"
    user.full_name = "Test User"
    return user


@pytest.fixture
def message_mock(user_mock):
    message = MagicMock()
    message.text = "Test message"
    message.chat.id = -1001234567890
    message.chat.title = "Test Group"
    message.from_user = user_mock
    message.message_id = 1
    return message


@pytest.mark.asyncio
async def test_handle_moderated_message_disabled_moderation(
    patched_db_conn, clean_db, message_mock
):
    with patch(
        "app.handlers.message_handlers.is_moderation_enabled"
    ) as mod_mock, patch(
        "app.handlers.message_handlers.is_member_in_group"
    ) as member_mock:
        mod_mock.return_value = False

        # Insert group directly into database
        async with clean_db.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO groups (group_id, moderation_enabled)
                VALUES ($1, $2)
            """,
                message_mock.chat.id,
                True,
            )

        await handle_moderated_message(message_mock)
        member_mock.assert_not_called()


@pytest.mark.asyncio
async def test_handle_spam_auto_delete(patched_db_conn, clean_db, message_mock):
    async with clean_db.acquire() as conn:
        # Create test admins
        await conn.execute(
            """
            INSERT INTO administrators (admin_id, username, delete_spam, credits)
            VALUES ($1, 'admin1', true, 100), ($2, 'admin2', true, 100)
        """,
            111111,
            222222,
        )

    with patch("app.handlers.message_handlers.bot.delete_message") as delete_mock:
        await handle_spam(message_mock)
        delete_mock.assert_called_once_with(
            message_mock.chat.id, message_mock.message_id
        )


@pytest.mark.asyncio
async def test_try_deduct_credits_failure(patched_db_conn, clean_db):
    with patch(
        "app.handlers.message_handlers.deduct_credits_from_admins"
    ) as deduct_mock, patch(
        "app.handlers.message_handlers.set_group_moderation"
    ) as set_mod_mock:
        deduct_mock.return_value = False
        chat_id = -1001234567890

        result = await try_deduct_credits(chat_id, 10, "test deduction")

        assert result is False
        set_mod_mock.assert_called_once_with(chat_id, False)
