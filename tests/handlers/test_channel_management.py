"""Tests for channel management (notify_channel_admins_and_leave, userbot fallback)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.exceptions import TelegramForbiddenError

from src.app.handlers.message.channel_management import (
    build_channel_instruction_message,
    build_channel_instruction_userbot_message,
    notify_channel_admins_and_leave,
)


class TestBuildChannelInstructionUserbotMessage:
    """Test userbot message builder includes preamble for unknown sender."""

    def test_includes_preamble_identifying_bot(self):
        """Preamble identifies the official bot and explains why from this account."""
        msg = build_channel_instruction_userbot_message(
            "Test Channel", None, "testchannel"
        )
        assert "@ai_antispam_blocker_bot" in msg
        assert "Сообщение от команды бота" in msg
        assert "не смог написать" in msg or "удалён" in msg

    def test_includes_instruction_body(self):
        """Instruction body is same as standard message."""
        body = build_channel_instruction_message(
            "Test", "https://t.me/discuss", "testchan"
        )
        userbot_msg = build_channel_instruction_userbot_message(
            "Test", "https://t.me/discuss", "testchan"
        )
        assert body in userbot_msg
        assert "Discussion Group" in userbot_msg or "discuss" in userbot_msg


@pytest.mark.asyncio
async def test_notify_channel_admins_and_leave_forbidden_fallback_userbot():
    """When primary flow raises TelegramForbiddenError and adding_user has username, userbot DM is attempted."""
    chat = MagicMock()
    chat.id = -1001297263491
    chat.title = "."
    chat.username = None
    chat.linked_chat_id = None

    bot = AsyncMock()
    bot.get_chat_administrators = AsyncMock(
        return_value=[]
    )  # notify_channel_admins succeeds
    bot.leave_chat = AsyncMock(
        side_effect=TelegramForbiddenError(
            MagicMock(), "Forbidden: bot is not a member of the channel chat"
        )
    )

    adding_user = MagicMock()
    adding_user.id = 12345
    adding_user.username = "channeladmin"
    adding_user.is_bot = False

    with (
        patch(
            "src.app.handlers.message.channel_management.get_discussion_username",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.app.handlers.message.channel_management.send_userbot_dm",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_send_userbot,
    ):
        await notify_channel_admins_and_leave(chat, bot, adding_user=adding_user)

        mock_send_userbot.assert_called_once()
        call_kwargs = mock_send_userbot.call_args.kwargs
        assert call_kwargs["username"] == "channeladmin"
        assert call_kwargs["user_id"] == 12345
        assert "@ai_antispam_blocker_bot" in call_kwargs["message"]


@pytest.mark.asyncio
async def test_notify_channel_admins_and_leave_forbidden_no_username_skips_userbot():
    """When primary fails but adding_user has no username, userbot DM is not attempted."""
    chat = MagicMock()
    chat.id = -1001297263491
    chat.title = "Test"
    chat.username = None
    chat.linked_chat_id = None

    bot = AsyncMock()
    bot.get_chat_administrators = AsyncMock(return_value=[])
    bot.leave_chat = AsyncMock(
        side_effect=TelegramForbiddenError(
            MagicMock(), "Forbidden: bot is not a member"
        )
    )

    adding_user = MagicMock()
    adding_user.id = 12345
    adding_user.username = None  # No username
    adding_user.is_bot = False

    with (
        patch(
            "src.app.handlers.message.channel_management.get_discussion_username",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.app.handlers.message.channel_management.send_userbot_dm",
            new_callable=AsyncMock,
        ) as mock_send_userbot,
    ):
        await notify_channel_admins_and_leave(chat, bot, adding_user=adding_user)

        mock_send_userbot.assert_not_called()


@pytest.mark.asyncio
async def test_notify_channel_admins_and_leave_forbidden_does_not_raise():
    """notify_channel_admins_and_leave does not propagate TelegramForbiddenError."""
    chat = MagicMock()
    chat.id = -1001297263491
    chat.title = "Test"
    chat.username = None
    chat.linked_chat_id = None

    bot = AsyncMock()
    bot.get_chat_administrators = AsyncMock(return_value=[])
    bot.leave_chat = AsyncMock(
        side_effect=TelegramForbiddenError(
            MagicMock(), "Forbidden: bot is not a member"
        )
    )

    with (
        patch(
            "src.app.handlers.message.channel_management.get_discussion_username",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.app.handlers.message.channel_management.send_userbot_dm",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        # Should not raise
        await notify_channel_admins_and_leave(chat, bot, adding_user=None)
