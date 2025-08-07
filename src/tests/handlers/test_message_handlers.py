from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ...app.handlers.message_handlers import (
    handle_moderated_message,
    handle_spam,
    try_deduct_credits,
)


@pytest.fixture(autouse=True)
def mock_bot():
    with patch("src.app.handlers.message_handlers.bot") as mock:
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
    message.caption = None
    message.chat.id = -1001234567890
    message.chat.title = "Test Group"
    message.from_user = user_mock
    message.message_id = 1
    message.photo = None
    message.video = None
    message.animation = None
    message.document = None
    message.sticker = None
    message.voice = None
    message.video_note = None
    return message


@pytest.fixture
def photo_message_mock(message_mock):
    message_mock.text = None
    message_mock.photo = [MagicMock()]  # Telegram sends array of PhotoSize
    return message_mock


@pytest.fixture
def photo_with_caption_mock(photo_message_mock):
    photo_message_mock.caption = "Test photo caption"
    return photo_message_mock


@pytest.mark.asyncio
async def test_handle_moderated_message_disabled_moderation(
    patched_db_conn, clean_db, message_mock
):
    with (
        patch("src.app.handlers.message_handlers.is_moderation_enabled") as mod_mock,
        patch("src.app.handlers.message_handlers.is_member_in_group") as member_mock,
    ):
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
async def test_handle_moderated_message_photo_no_caption(
    patched_db_conn, clean_db, photo_message_mock
):
    with (
        patch("src.app.handlers.message_handlers.is_moderation_enabled") as mod_mock,
        patch("src.app.handlers.message_handlers.is_member_in_group") as member_mock,
        patch("src.app.handlers.message_handlers.is_spam") as spam_mock,
    ):
        mod_mock.return_value = True
        member_mock.return_value = False
        spam_mock.return_value = 0

        await handle_moderated_message(photo_message_mock)

        # Проверяем, что для проверки спама использовался маркер [MEDIA_MESSAGE]
        spam_mock.assert_called_once()
        assert spam_mock.call_args[1]["comment"] == "[MEDIA_MESSAGE]"


@pytest.mark.asyncio
async def test_handle_moderated_message_photo_with_caption(
    patched_db_conn, clean_db, photo_with_caption_mock
):
    with (
        patch("src.app.handlers.message_handlers.is_moderation_enabled") as mod_mock,
        patch("src.app.handlers.message_handlers.is_member_in_group") as member_mock,
        patch("src.app.handlers.message_handlers.is_spam") as spam_mock,
    ):
        mod_mock.return_value = True
        member_mock.return_value = False
        spam_mock.return_value = 0

        await handle_moderated_message(photo_with_caption_mock)

        # Проверяем, что для проверки спама использовалась подпись к фото
        spam_mock.assert_called_once()
        assert spam_mock.call_args[1]["comment"] == "Test photo caption"


@pytest.mark.asyncio
async def test_handle_moderated_message_with_reply_markup(
    patched_db_conn, clean_db, message_mock
):
    with (
        patch("src.app.handlers.message_handlers.is_moderation_enabled") as mod_mock,
        patch("src.app.handlers.message_handlers.is_member_in_group") as member_mock,
        patch("src.app.handlers.message_handlers.is_spam") as spam_mock,
        patch("src.app.handlers.message_handlers.try_deduct_credits") as deduct_mock,
        patch("src.app.handlers.message_handlers.handle_spam") as handle_spam_mock,
    ):
        # Setup mocks
        mod_mock.return_value = True
        member_mock.return_value = False
        deduct_mock.return_value = True

        # Add reply markup to message
        message_mock.reply_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Test Button", url="https://test.com")]
            ]
        )

        result = await handle_moderated_message(message_mock)

        # Verify message was marked as spam
        spam_mock.assert_not_called()  # is_spam shouldn't be called since we auto-mark as spam
        handle_spam_mock.assert_called_once_with(message_mock)
        assert result == "message_spam_deleted"


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

    with patch("src.app.handlers.message_handlers.bot.delete_message") as delete_mock:
        await handle_spam(message_mock)
        delete_mock.assert_called_once_with(
            message_mock.chat.id, message_mock.message_id
        )


@pytest.mark.asyncio
async def test_try_deduct_credits_failure(patched_db_conn, clean_db):
    with (
        patch(
            "src.app.handlers.message_handlers.deduct_credits_from_admins"
        ) as deduct_mock,
        patch("src.app.handlers.message_handlers.set_group_moderation") as set_mod_mock,
    ):
        deduct_mock.return_value = 0  # Return 0 instead of False to indicate failure
        chat_id = -1001234567890

        result = await try_deduct_credits(chat_id, 10, "test deduction")

        assert result is False
        set_mod_mock.assert_called_once_with(chat_id, False)
