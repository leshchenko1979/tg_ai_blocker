"""Tests for message processing pipeline."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.app.handlers.message.pipeline import process_spam_or_approve


@pytest.fixture
def mock_message():
    """Create a mock message for testing."""
    message = MagicMock()
    message.message_id = 12345
    message.chat.id = -1001234567890
    message.chat.title = "Test Group"

    user = MagicMock()
    user.id = 67890
    user.full_name = "Test User"
    user.username = "testuser"
    message.from_user = user
    message.sender_chat = None

    return message


@pytest.fixture
def mock_message_context_result():
    """Create a mock MessageContextResult."""
    result = MagicMock()
    result.message_text = "Test message"
    result.is_story = False
    result.context = None
    return result


class TestProcessSpamOrApprove:
    """Test process_spam_or_approve score thresholds and skip_auto_delete."""

    @pytest.mark.asyncio
    async def test_score_50_approves_user(
        self, mock_message, mock_message_context_result
    ):
        """Score <= 50 should approve user, not call handle_spam."""
        with (
            patch(
                "src.app.handlers.message.pipeline.try_deduct_credits",
                new_callable=AsyncMock,
            ) as mock_deduct,
            patch(
                "src.app.handlers.message.pipeline.add_member",
                new_callable=AsyncMock,
            ) as mock_add_member,
            patch(
                "src.app.handlers.message.pipeline.handle_spam",
                new_callable=AsyncMock,
            ) as mock_handle_spam,
        ):
            mock_deduct.return_value = True

            result = await process_spam_or_approve(
                mock_message,
                50,
                [123],
                "reason",
                mock_message_context_result,
            )

            assert result == "message_user_approved"
            mock_handle_spam.assert_not_called()
            mock_add_member.assert_called_once()

    @pytest.mark.asyncio
    async def test_score_75_low_confidence_skip_auto_delete(
        self, mock_message, mock_message_context_result
    ):
        """Score 50 < score < 90 should call handle_spam with skip_auto_delete=True."""
        with (
            patch(
                "src.app.handlers.message.pipeline.try_deduct_credits",
                new_callable=AsyncMock,
            ) as mock_deduct,
            patch(
                "src.app.handlers.message.pipeline.handle_spam",
                new_callable=AsyncMock,
            ) as mock_handle_spam,
            patch(
                "src.app.handlers.message.pipeline.load_config",
            ) as mock_load_config,
        ):
            mock_deduct.return_value = True
            mock_load_config.return_value = {
                "spam": {"high_confidence_threshold": 90}
            }

            result = await process_spam_or_approve(
                mock_message,
                75,
                [123],
                "reason",
                mock_message_context_result,
            )

            mock_handle_spam.assert_called_once()
            call_kwargs = mock_handle_spam.call_args[1]
            assert call_kwargs["skip_auto_delete"] is True

    @pytest.mark.asyncio
    async def test_score_90_high_confidence_no_skip_auto_delete(
        self, mock_message, mock_message_context_result
    ):
        """Score >= 90 should call handle_spam with skip_auto_delete=False."""
        with (
            patch(
                "src.app.handlers.message.pipeline.try_deduct_credits",
                new_callable=AsyncMock,
            ) as mock_deduct,
            patch(
                "src.app.handlers.message.pipeline.handle_spam",
                new_callable=AsyncMock,
            ) as mock_handle_spam,
            patch(
                "src.app.handlers.message.pipeline.load_config",
            ) as mock_load_config,
        ):
            mock_deduct.return_value = True
            mock_load_config.return_value = {
                "spam": {"high_confidence_threshold": 90}
            }

            result = await process_spam_or_approve(
                mock_message,
                90,
                [123],
                "reason",
                mock_message_context_result,
            )

            mock_handle_spam.assert_called_once()
            call_kwargs = mock_handle_spam.call_args[1]
            assert call_kwargs["skip_auto_delete"] is False

    @pytest.mark.asyncio
    async def test_score_100_high_confidence_no_skip_auto_delete(
        self, mock_message, mock_message_context_result
    ):
        """Score 100 should call handle_spam with skip_auto_delete=False."""
        with (
            patch(
                "src.app.handlers.message.pipeline.try_deduct_credits",
                new_callable=AsyncMock,
            ) as mock_deduct,
            patch(
                "src.app.handlers.message.pipeline.handle_spam",
                new_callable=AsyncMock,
            ) as mock_handle_spam,
            patch(
                "src.app.handlers.message.pipeline.load_config",
            ) as mock_load_config,
        ):
            mock_deduct.return_value = True
            mock_load_config.return_value = {
                "spam": {"high_confidence_threshold": 90}
            }

            result = await process_spam_or_approve(
                mock_message,
                100,
                [123],
                "reason",
                mock_message_context_result,
            )

            mock_handle_spam.assert_called_once()
            call_kwargs = mock_handle_spam.call_args[1]
            assert call_kwargs["skip_auto_delete"] is False

    @pytest.mark.asyncio
    async def test_score_uses_config_threshold(
        self, mock_message, mock_message_context_result
    ):
        """Custom threshold from config: score 75 with threshold 80 -> skip_auto_delete=True."""
        with (
            patch(
                "src.app.handlers.message.pipeline.try_deduct_credits",
                new_callable=AsyncMock,
            ) as mock_deduct,
            patch(
                "src.app.handlers.message.pipeline.handle_spam",
                new_callable=AsyncMock,
            ) as mock_handle_spam,
            patch(
                "src.app.handlers.message.pipeline.load_config",
            ) as mock_load_config,
        ):
            mock_deduct.return_value = True
            mock_load_config.return_value = {
                "spam": {"high_confidence_threshold": 80}
            }

            await process_spam_or_approve(
                mock_message,
                75,
                [123],
                "reason",
                mock_message_context_result,
            )

            call_kwargs = mock_handle_spam.call_args[1]
            assert call_kwargs["skip_auto_delete"] is True

    @pytest.mark.asyncio
    async def test_score_insufficient_credits(
        self, mock_message, mock_message_context_result
    ):
        """When try_deduct_credits fails for spam, return message_insufficient_credits."""
        with (
            patch(
                "src.app.handlers.message.pipeline.try_deduct_credits",
                new_callable=AsyncMock,
            ) as mock_deduct,
            patch(
                "src.app.handlers.message.pipeline.handle_spam",
                new_callable=AsyncMock,
            ) as mock_handle_spam,
        ):
            mock_deduct.return_value = False

            result = await process_spam_or_approve(
                mock_message,
                95,
                [123],
                "reason",
                mock_message_context_result,
            )

            assert result == "message_insufficient_credits"
            mock_handle_spam.assert_not_called()
