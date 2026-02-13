"""Unit tests for /start and /help command handlers (no integration)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.app.types import ContextStatus
from src.app.handlers.command_handlers import handle_help_command


def _make_start_message():
    message = MagicMock()
    message.text = "/start"
    message.chat.type = "private"
    user = MagicMock()
    user.id = 12345
    user.username = "testuser"
    message.from_user = user
    message.reply = AsyncMock()
    message.answer = AsyncMock()
    return message


class TestStartCommandNewUser:
    """Test /start handler for new users (welcome message and linked channel offer)."""

    @pytest.mark.asyncio
    async def test_sends_welcome_without_offer_when_no_linked_channel(self):
        message = _make_start_message()
        base_welcome = "Welcome!"
        config = {
            "start_welcome_text": base_welcome,
        }
        mock_chat = MagicMock()
        mock_chat.personal_chat = None
        mock_chat.bio = None

        with (
            patch(
                "src.app.handlers.command_handlers.initialize_new_admin",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "src.app.handlers.command_handlers.update_admin_username_if_needed",
                new_callable=AsyncMock,
            ),
            patch(
                "src.app.handlers.command_handlers.load_config",
                return_value=config,
            ),
            patch(
                "src.app.handlers.command_handlers.collect_user_context",
                new_callable=AsyncMock,
            ) as mock_collect,
            patch(
                "src.app.handlers.command_handlers.bot",
            ) as mock_bot,
        ):
            mock_collect.return_value = MagicMock(
                linked_channel=MagicMock(
                    status=ContextStatus.EMPTY,
                    content=None,
                )
            )
            mock_bot.get_chat = AsyncMock(return_value=mock_chat)

            result = await handle_help_command(message)

        assert result == "command_start_new_user_sent"
        message.reply.assert_awaited_once()
        sent_text = message.reply.call_args[0][0]
        call_kw = message.reply.call_args[1]
        assert call_kw["parse_mode"] == "HTML"
        assert base_welcome in sent_text
        message.answer.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_welcome_with_offer_when_linked_channel_found(self):
        message = _make_start_message()
        base_welcome = "Welcome!"
        config = {
            "start_welcome_text": base_welcome,
            "start_linked_channel_offer_template": "Channel: {channel_display}",
        }
        channel_id = -1001234567890
        mock_chat = MagicMock()
        mock_chat.title = "My Channel"
        mock_chat.username = "mychannel"
        mock_chat.id = channel_id
        mock_chat.personal_chat = None
        mock_chat.bio = None

        with (
            patch(
                "src.app.handlers.command_handlers.initialize_new_admin",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "src.app.handlers.command_handlers.update_admin_username_if_needed",
                new_callable=AsyncMock,
            ),
            patch(
                "src.app.handlers.command_handlers.load_config",
                return_value=config,
            ),
            patch(
                "src.app.handlers.command_handlers.collect_user_context",
                new_callable=AsyncMock,
            ) as mock_collect,
            patch(
                "src.app.handlers.command_handlers.bot",
            ) as mock_bot,
        ):
            mock_summary = MagicMock()
            mock_summary.channel_id = channel_id
            mock_collect.return_value = MagicMock(
                linked_channel=MagicMock(
                    status=ContextStatus.FOUND,
                    content=mock_summary,
                )
            )
            mock_bot.get_chat = AsyncMock(return_value=mock_chat)

            result = await handle_help_command(message)

        assert result == "command_start_new_user_sent"
        # First message: welcome
        message.reply.assert_awaited_once()
        sent_welcome = message.reply.call_args[0][0]
        assert base_welcome in sent_welcome

        # Second message: offer
        message.answer.assert_awaited_once()
        offer_text = message.answer.call_args[0][0]
        call_kw = message.answer.call_args[1]
        assert "My Channel" in offer_text
        assert "mychannel" in offer_text
        assert call_kw["reply_markup"] is not None

    @pytest.mark.asyncio
    async def test_sends_base_welcome_on_collect_error(self):
        message = _make_start_message()
        base_welcome = "Welcome!"
        config = {"start_welcome_text": base_welcome}

        with (
            patch(
                "src.app.handlers.command_handlers.initialize_new_admin",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "src.app.handlers.command_handlers.update_admin_username_if_needed",
                new_callable=AsyncMock,
            ),
            patch(
                "src.app.handlers.command_handlers.load_config",
                return_value=config,
            ),
            patch(
                "src.app.handlers.command_handlers.collect_user_context",
                new_callable=AsyncMock,
                side_effect=Exception("MTProto error"),
            ),
            patch(
                "src.app.handlers.command_handlers.bot",
            ) as mock_bot,
        ):
            mock_bot.get_chat = AsyncMock(side_effect=Exception("API error"))

            result = await handle_help_command(message)

        assert result == "command_start_new_user_sent"
        message.reply.assert_awaited_once()
        sent_text = message.reply.call_args[0][0]
        assert sent_text == base_welcome
        message.answer.assert_not_called()
