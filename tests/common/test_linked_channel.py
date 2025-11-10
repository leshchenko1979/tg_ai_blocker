"""Test linked channel extraction after refactoring to direct MTProto approach."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.app.common.linked_channel import (
    collect_linked_channel_summary,
    LinkedChannelSummary,
)


class TestLinkedChannelExtraction:
    """Test the refactored linked channel extraction that goes directly to MTProto."""

    @pytest.mark.asyncio
    async def test_collect_linked_channel_summary_uses_mtproto_directly(self):
        """Test that collect_linked_channel_summary goes directly to MTProto without bot calls."""
        user_id = 12345

        # Mock MTProto client and response
        mock_client = MagicMock()
        mock_client.call = AsyncMock(
            return_value={"full_user": {"linked_chat_id": 67890}}
        )

        # Mock all MTProto calls
        mock_client.call.side_effect = [
            # First call: getFullUser
            {"full_user": {"personal_channel_id": 67890}},
            # Second call: getFullChat
            {"full_chat": {"participants_count": 1000}},
            # Third call: messages.getHistory (for post age calculation)
            {"messages": [], "count": 0},  # No messages, channel is empty
        ]

        with patch(
            "src.app.common.linked_channel.get_mtproto_client", return_value=mock_client
        ):
            result = await collect_linked_channel_summary(user_id)

            # Verify MTProto was called (should be called 3 times: user + channel + history)
            assert mock_client.call.call_count == 3

            # Verify we got the expected result
            assert isinstance(result, LinkedChannelSummary)
            assert result.subscribers == 1000
            assert (
                result.total_posts == 0
            )  # From the mocked messages.getHistory response
            assert result.post_age_delta is None  # Channel has no posts

    @pytest.mark.asyncio
    async def test_collect_linked_channel_summary_no_linked_channel(self):
        """Test handling of users without linked channels."""
        user_id = 12345

        # Mock MTProto client - user has no linked channel
        mock_client = MagicMock()
        mock_client.call = AsyncMock(
            return_value={
                "full_user": {}  # No linked_chat_id
            }
        )

        with patch(
            "src.app.common.linked_channel.get_mtproto_client", return_value=mock_client
        ):
            result = await collect_linked_channel_summary(user_id)

            # Should return None when no linked channel
            assert result is None

            # Verify MTProto was called once (only for user, not channel)
            assert mock_client.call.call_count == 1
