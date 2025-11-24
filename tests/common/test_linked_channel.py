"""Test linked channel extraction after refactoring to direct MTProto approach."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.app.common.linked_channel import (
    collect_linked_channel_summary,
    collect_channel_summary_by_id,
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

    @pytest.mark.asyncio
    async def test_collect_channel_summary_by_id_uses_username(self):
        """Test that collect_channel_summary_by_id uses username if provided."""
        channel_id = -10012345
        username = "testchannel"

        mock_client = MagicMock()
        mock_client.call = AsyncMock()

        # side effects for calls
        mock_client.call.side_effect = [
            # getFullChannel
            {"full_chat": {"participants_count": 500}},
            # getHistory
            {"messages": [], "count": 0},
        ]

        with patch(
            "src.app.common.linked_channel.get_mtproto_client", return_value=mock_client
        ):
            await collect_channel_summary_by_id(channel_id, username=username)

            # Verify first call used username
            assert mock_client.call.call_count >= 1
            call_args = mock_client.call.call_args_list[0]
            assert call_args.args[0] == "channels.getFullChannel"
            assert call_args.kwargs["params"]["channel"] == username

    @pytest.mark.asyncio
    async def test_collect_channel_summary_by_id_fallback_to_id(self):
        """Test that collect_channel_summary_by_id falls back to ID if username fails."""
        channel_id = -10012345
        mtproto_id = 12345
        username = "testchannel"

        mock_client = MagicMock()
        mock_client.call = AsyncMock()

        from src.app.common.mtproto_client import MtprotoHttpError

        # side effects for calls
        mock_client.call.side_effect = [
            # getFullChannel with username -> fails
            MtprotoHttpError(500, {"error": "Username invalid"}),
            # getFullChannel with ID -> succeeds
            {"full_chat": {"participants_count": 500}},
            # getHistory
            {"messages": [], "count": 0},
        ]

        with patch(
            "src.app.common.linked_channel.get_mtproto_client", return_value=mock_client
        ):
            await collect_channel_summary_by_id(channel_id, username=username)

            # Verify called twice for getFullChannel (username then ID)
            assert mock_client.call.call_count >= 2

            # First call with username
            call1 = mock_client.call.call_args_list[0]
            assert call1.args[0] == "channels.getFullChannel"
            assert call1.kwargs["params"]["channel"] == username

            # Second call with ID
            call2 = mock_client.call.call_args_list[1]
            assert call2.args[0] == "channels.getFullChannel"
            assert call2.kwargs["params"]["channel"] == mtproto_id
