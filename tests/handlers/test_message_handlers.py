from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from common.database.models import User
from handlers.message_handlers import (
    handle_moderated_message,
    handle_spam,
    try_deduct_credits,
)


@pytest.fixture(autouse=True)
def mock_logger():
    with patch("handlers.message_handlers.get_yandex_logger") as mock:
        logger_mock = MagicMock()
        mock.return_value = logger_mock
        yield logger_mock


@pytest.fixture(autouse=True)
def mock_bot():
    with patch("handlers.message_handlers.bot") as mock:
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
async def test_handle_moderated_message_disabled_moderation(message_mock):
    with patch("handlers.message_handlers.ensure_group_exists") as ensure_mock, patch(
        "handlers.message_handlers.is_moderation_enabled"
    ) as mod_mock, patch("handlers.message_handlers.is_member_in_group") as member_mock:
        mod_mock.return_value = False
        ensure_mock.return_value = True

        await handle_moderated_message(message_mock)

        ensure_mock.assert_called_once()
        member_mock.assert_not_called()


@pytest.mark.asyncio
async def test_handle_spam_auto_delete(message_mock):
    with patch("handlers.message_handlers.get_user") as get_user_mock, patch(
        "handlers.message_handlers.bot.delete_message"
    ) as delete_mock:
        admin1 = {
            "user_id": 111111,
            "username": "admin1",
            "first_name": "Admin1",
            "delete_spam": True,
            "credits": 100,
            "is_active": True,
            "groups": [],
        }
        admin2 = {
            "user_id": 222222,
            "username": "admin2",
            "first_name": "Admin2",
            "delete_spam": True,
            "credits": 100,
            "is_active": True,
            "groups": [],
        }

        get_user_mock.side_effect = [User(**admin1), User(**admin2)]

        await handle_spam(message_mock)

        delete_mock.assert_called_once_with(
            message_mock.chat.id, message_mock.message_id
        )


@pytest.mark.asyncio
async def test_try_deduct_credits_failure():
    with patch(
        "handlers.message_handlers.deduct_credits_from_admins"
    ) as deduct_mock, patch(
        "handlers.message_handlers.set_group_moderation"
    ) as set_mod_mock:
        deduct_mock.return_value = False
        chat_id = -1001234567890

        result = await try_deduct_credits(chat_id, 10, "test deduction")

        assert result is False
        set_mod_mock.assert_called_once_with(chat_id, False)
