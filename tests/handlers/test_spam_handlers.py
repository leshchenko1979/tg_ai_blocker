import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.app.handlers.handle_spam import (
    format_admin_notification_message,
    handle_spam,
    handle_spam_message_deletion,
    notify_spam_contacts_via_mcp,
)
from src.app.spam.message_context import collect_message_context
from src.app.types import (
    ContextStatus,
    MessageNotificationContext,
)
from tests.conftest import MockTelegramBadRequest


class TestSpamDeletion:
    """Test spam message deletion and permission error handling."""

    @pytest.mark.asyncio
    async def test_successful_spam_deletion(self, mock_message):
        """Test successful spam message deletion."""
        with (
            patch("src.app.handlers.handle_spam.bot") as mock_bot,
        ):
            mock_bot.delete_message = AsyncMock()

            await handle_spam_message_deletion(mock_message, [123456789])

            mock_bot.delete_message.assert_called_once_with(
                mock_message.chat.id, mock_message.message_id
            )

    @pytest.mark.asyncio
    async def test_spam_deletion_non_permission_error(self, mock_message):
        """Test spam deletion failure due to non-permission error."""
        with (
            patch("src.app.handlers.handle_spam.bot") as mock_bot,
            patch("src.app.handlers.handle_spam.logger") as mock_logger,
            patch(
                "src.app.handlers.handle_spam._get_notification_lang",
                new_callable=AsyncMock,
                return_value="en",
            ),
        ):
            mock_bot.delete_message = AsyncMock(
                side_effect=MockTelegramBadRequest("Some other error")
            )

            await handle_spam_message_deletion(mock_message, [123456789])

            mock_bot.delete_message.assert_called_once_with(
                mock_message.chat.id, mock_message.message_id
            )
            # Should log the error, but not notify admins
            assert mock_logger.warning.called

    @pytest.mark.asyncio
    async def test_spam_deletion_permission_error_admin_notification_success(
        self, mock_message
    ):
        """Test spam deletion failure due to permission error with successful admin notification."""
        mock_admin = MagicMock()
        mock_admin.language_code = "ru"

        with (
            patch("src.app.handlers.handle_spam.bot") as mock_bot,
            patch(
                "src.app.handlers.handle_spam.get_admin",
                new_callable=AsyncMock,
                return_value=mock_admin,
            ),
            patch(
                "src.app.handlers.handle_spam.set_no_rights_detected_at",
                new_callable=AsyncMock,
            ),
            patch(
                "src.app.handlers.handle_spam.notify_admins_with_fallback_and_cleanup"
            ) as mock_notify,
        ):
            # Mock permission error
            permission_error = MockTelegramBadRequest(
                "Not enough rights to delete message"
            )
            mock_bot.delete_message = AsyncMock(side_effect=permission_error)

            # Mock successful notification
            mock_notify.return_value = {
                "notified_private": [111],
                "group_notified": False,
            }

            await handle_spam_message_deletion(mock_message, [111, 222])

            mock_bot.delete_message.assert_called_once_with(
                mock_message.chat.id, mock_message.message_id
            )

            # Should notify admins about missing rights
            mock_notify.assert_called_once()
            call_args, call_kwargs = mock_notify.call_args
            # call_args[0] is bot, call_args[1] is admin_ids, call_args[2] is group_id
            assert call_args[1] == [111, 222]  # admin_ids
            assert call_args[2] == mock_message.chat.id  # group_id
            assert (
                "У меня нет права удалять спам-сообщения"
                in call_kwargs["private_message"]
            )

    @pytest.mark.asyncio
    async def test_spam_deletion_permission_error_notification_failure(
        self, mock_message
    ):
        """Test spam deletion failure due to permission error with failed admin notification."""
        with (
            patch("src.app.handlers.handle_spam.bot") as mock_bot,
            patch(
                "src.app.handlers.handle_spam.set_no_rights_detected_at",
                new_callable=AsyncMock,
            ),
            patch(
                "src.app.handlers.handle_spam.notify_admins_with_fallback_and_cleanup"
            ) as mock_notify,
            patch(
                "src.app.handlers.handle_spam._get_notification_lang",
                new_callable=AsyncMock,
                return_value="en",
            ),
            patch("src.app.handlers.handle_spam.logger") as mock_logger,
        ):
            # Mock permission error
            permission_error = MockTelegramBadRequest(
                "Need administrator rights to delete messages"
            )
            mock_bot.delete_message = AsyncMock(side_effect=permission_error)

            # Mock notification failure that triggers cleanup
            mock_notify.side_effect = Exception("All notification methods failed")

            await handle_spam_message_deletion(mock_message, [111, 222])

            mock_bot.delete_message.assert_called_once_with(
                mock_message.chat.id, mock_message.message_id
            )

            # Should attempt to notify admins
            mock_notify.assert_called_once()

            # Should log the notification failure
            warning_calls = [
                call
                for call in mock_logger.warning.call_args_list
                if "Failed to notify admins about missing rights" in str(call)
            ]
            assert len(warning_calls) == 1

    @pytest.mark.asyncio
    async def test_spam_deletion_permission_error_no_group(self, mock_message):
        """Test spam deletion failure due to permission error when group not found."""
        with (
            patch("src.app.handlers.handle_spam.bot") as mock_bot,
            patch(
                "src.app.handlers.handle_spam.set_no_rights_detected_at",
                new_callable=AsyncMock,
            ),
            patch(
                "src.app.handlers.handle_spam.notify_admins_with_fallback_and_cleanup"
            ) as mock_notify,
        ):
            # Mock permission error
            permission_error = MockTelegramBadRequest("Chat admin required")
            mock_bot.delete_message = AsyncMock(side_effect=permission_error)

            # Simulate no admins available
            await handle_spam_message_deletion(mock_message, [])

            mock_bot.delete_message.assert_called_once_with(
                mock_message.chat.id, mock_message.message_id
            )

            # Should not attempt to notify admins if group not found
            mock_notify.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_sender_chat_spam_check_trigger(self, mock_message):
        """
        Test that messages with sender_chat trigger collect_channel_summary_by_id
        and the result is passed to is_spam.
        """
        # Setup mock message with sender_chat
        mock_message.sender_chat = MagicMock()
        mock_message.sender_chat.id = -1002916411724  # Example channel ID
        mock_message.sender_chat.title = "Channel Bot"
        mock_message.sender_chat.type = "channel"
        mock_message.chat.id = -1001503592176  # Different group ID
        mock_message.reply_to_message = None  # No reply in this test

        # Mock group
        mock_group = MagicMock()
        mock_group.admin_ids = [123]

        with (
            patch("src.app.common.bot.bot") as mock_bot,
            patch(
                "src.app.common.mtproto_client.MtprotoHttpClient.call",
                new_callable=AsyncMock,
            ) as mock_mtproto_call,
        ):
            # Mock get_chat to return an object with description = None
            mock_chat_info = MagicMock()
            mock_chat_info.description = None
            mock_bot.get_chat = AsyncMock(return_value=mock_chat_info)

            # Mock MTProto client call to prevent HTTP requests
            mock_mtproto_call.return_value = {
                "subscribers": 150,
                "total_posts": 25,
                "post_age_delta": 2,
                "recent_posts": ["Test post content"],
            }

            result = await collect_message_context(mock_message)
            message_text, is_story, context = (
                result.message_text,
                result.is_story,
                result.context,
            )

            # Verify MTProto call was made (indicating channel context collection)
            assert mock_mtproto_call.called

            # Verify context was collected correctly
            assert context.name == "Channel Bot"  # sender_chat.title
            # Bio comes from message.chat.description (mock object in test)
            assert (
                context.linked_channel is not None
            )  # Channels now get linked channel analysis
            assert context.linked_channel.status == ContextStatus.FOUND
            assert context.stories is None  # No stories collection for channels
            assert context.reply is None  # No reply in this test


class TestHandleSpamSkipAutoDelete:
    """Test handle_spam with skip_auto_delete (low-confidence spam flow)."""

    @pytest.mark.asyncio
    async def test_skip_auto_delete_no_deletion_no_ban(self, mock_message):
        """With skip_auto_delete=True, should not delete message or ban user."""
        with (
            patch(
                "src.app.handlers.handle_spam.check_admin_delete_preferences",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "src.app.handlers.handle_spam.notify_admins",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "src.app.handlers.handle_spam.handle_spam_message_deletion",
                new_callable=AsyncMock,
            ) as mock_delete,
            patch(
                "src.app.handlers.handle_spam.ban_user_for_spam",
                new_callable=AsyncMock,
            ) as mock_ban,
        ):
            result = await handle_spam(
                mock_message,
                [123],
                reason="test",
                skip_auto_delete=True,
            )

            assert result == "spam_admins_notified"
            mock_delete.assert_not_called()
            mock_ban.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_auto_delete_notify_with_both_buttons(self, mock_message):
        """With skip_auto_delete=True, notify_admins receives all_admins_delete=False."""
        with (
            patch(
                "src.app.handlers.handle_spam.check_admin_delete_preferences",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "src.app.handlers.handle_spam.notify_admins",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_notify,
        ):
            await handle_spam(
                mock_message,
                [123],
                reason="test",
                skip_auto_delete=True,
            )

            mock_notify.assert_called_once()
            call_args = mock_notify.call_args[0]
            # all_admins_delete is the second positional arg (index 1)
            assert call_args[1] is False  # effective_all_admins_delete


class TestFormatAdminNotificationMessage:
    """Test format_admin_notification_message with low-confidence not-spam."""

    def test_low_confidence_not_spam_uses_review_title_and_hint(self):
        """With is_low_confidence_not_spam=True, uses review title and confidence hint."""
        context = MessageNotificationContext(
            effective_user_id=123,
            content_text="Test content",
            chat_title="Test Group",
            chat_username="testgroup",
            is_channel_sender=False,
            violator_name="Test User",
            violator_username="testuser",
            forward_source="",
            message_link="",
            entity_name="Test User",
            entity_type="user",
            entity_username="testuser",
        )
        result = format_admin_notification_message(
            context,
            all_admins_delete=False,
            reason="AI reason",
            lang="en",
            is_low_confidence_not_spam=True,
            confidence=10,
        )
        assert "Low confidence" in result
        assert "10" in result
        assert "INTRUSION" not in result

    def test_spam_needs_confirmation_uses_confirmation_title(self):
        """With is_low_confidence_not_spam=False and all_admins_delete=False, uses needs_confirmation_title."""
        context = MessageNotificationContext(
            effective_user_id=123,
            content_text="Test content",
            chat_title="Test Group",
            chat_username="testgroup",
            is_channel_sender=False,
            violator_name="Test User",
            violator_username="testuser",
            forward_source="",
            message_link="",
            entity_name="Test User",
            entity_type="user",
            entity_username="testuser",
        )
        result = format_admin_notification_message(
            context,
            all_admins_delete=False,
            reason="Spam detected",
            lang="en",
            is_low_confidence_not_spam=False,
        )
        assert "Confirm" in result


class TestNotifySpamContactsFeatureFlag:
    @pytest.mark.asyncio
    async def test_notify_spam_contacts_skips_when_flag_disabled(self, mock_message):
        context = MagicMock()
        context.channel_users = []

        with (
            patch(
                "src.app.handlers.handle_spam.spam_notify_spammers_via_mcp_enabled",
                return_value=False,
            ),
            patch(
                "src.app.handlers.handle_spam.send_mcp_message_to_user",
                new_callable=AsyncMock,
            ) as mock_send,
        ):
            await notify_spam_contacts_via_mcp(
                mock_message, reason="test reason", message_context_result=context
            )

        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_notify_spam_contacts_sends_when_flag_enabled(self, mock_message):
        context = MagicMock()
        context.channel_users = []
        mock_message.sender_chat = None
        mock_message.from_user.id = 12345
        mock_message.from_user.username = "spammer"

        with (
            patch(
                "src.app.handlers.handle_spam.spam_notify_spammers_via_mcp_enabled",
                return_value=True,
            ),
            patch(
                "src.app.handlers.handle_spam.send_mcp_message_to_user",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_send,
        ):
            await notify_spam_contacts_via_mcp(
                mock_message, reason="test reason", message_context_result=context
            )

        mock_send.assert_called_once()

    """Test format_admin_notification_message with is_low_confidence_not_spam."""

    def test_low_confidence_not_spam_uses_review_title(self):
        """With is_low_confidence_not_spam=True, uses review_low_confidence_title."""
        context = MessageNotificationContext(
            effective_user_id=123,
            content_text="Test message",
            chat_title="Test Group",
            chat_username="testgroup",
            is_channel_sender=False,
            violator_name="User",
            violator_username="testuser",
            forward_source="",
            message_link="",
            entity_name="User",
            entity_type="user",
            entity_username="testuser",
        )
        result = format_admin_notification_message(
            context,
            all_admins_delete=False,
            reason="AI uncertain",
            lang="en",
            is_low_confidence_not_spam=True,
            confidence=10,
        )
        assert "Low confidence" in result
        assert "10" in result
        assert "INTRUSION" not in result


class TestFormatAdminNotificationMessage:
    """Test format_admin_notification_message with is_low_confidence_not_spam."""

    @pytest.fixture
    def notification_context(self):
        """Create a minimal MessageNotificationContext for testing."""
        return MessageNotificationContext(
            effective_user_id=67890,
            content_text="Test message content",
            chat_title="Test Group",
            chat_username="testgroup",
            is_channel_sender=False,
            violator_name="Test User",
            violator_username="testuser",
            forward_source="",
            message_link="https://t.me/c/123/456",
            entity_name="Test User",
            entity_type="user",
            entity_username="testuser",
        )

    def test_low_confidence_not_spam_uses_review_title(self, notification_context):
        """With is_low_confidence_not_spam=True, uses review_low_confidence_title."""
        result = format_admin_notification_message(
            notification_context,
            all_admins_delete=False,
            reason="AI uncertain",
            lang="en",
            is_low_confidence_not_spam=True,
            confidence=10,
        )
        assert "Low confidence" in result
        assert "10" in result

    def test_spam_needs_confirmation_uses_confirmation_title(
        self, notification_context
    ):
        """With is_low_confidence_not_spam=False, uses needs_confirmation_title."""
        result = format_admin_notification_message(
            notification_context,
            all_admins_delete=False,
            reason="Spam detected",
            lang="en",
            is_low_confidence_not_spam=False,
        )
        assert "Confirm" in result


class TestFormatAdminNotificationMessage:
    """Test format_admin_notification_message with is_low_confidence_not_spam."""

    @pytest.fixture
    def minimal_context(self):
        """Create minimal MessageNotificationContext for testing."""
        return MessageNotificationContext(
            effective_user_id=67890,
            content_text="Test message",
            chat_title="Test Group",
            chat_username="testgroup",
            is_channel_sender=False,
            violator_name="Test User",
            violator_username="testuser",
            forward_source="",
            message_link="",
            entity_name="Test User",
            entity_type="user",
            entity_username="testuser",
        )

    def test_low_confidence_not_spam_uses_review_title(self, minimal_context):
        """With is_low_confidence_not_spam=True, uses review_low_confidence_title."""
        result = format_admin_notification_message(
            minimal_context,
            all_admins_delete=False,
            reason="LLM uncertain",
            lang="en",
            is_low_confidence_not_spam=True,
            confidence=10,
        )
        assert "Low confidence" in result
        assert "INTRUSION" not in result
        assert "10" in result


class TestFormatAdminNotificationMessage:
    """Test format_admin_notification_message with is_low_confidence_not_spam."""

    @pytest.fixture
    def context(self):
        """Minimal MessageNotificationContext for tests."""
        return MessageNotificationContext(
            effective_user_id=67890,
            content_text="Test message",
            chat_title="Test Group",
            chat_username="testgroup",
            is_channel_sender=False,
            violator_name="Test User",
            violator_username="testuser",
            forward_source="",
            message_link="",
            entity_name="Test User",
            entity_type="user",
            entity_username="testuser",
        )

    def test_low_confidence_not_spam_uses_review_title(self, context):
        """With is_low_confidence_not_spam=True, uses review_low_confidence_title."""
        result = format_admin_notification_message(
            context,
            all_admins_delete=False,
            reason="AI uncertain",
            lang="en",
            is_low_confidence_not_spam=True,
            confidence=10,
        )
        assert "Low confidence" in result or "low confidence" in result
        assert "10" in result  # confidence in hint
        assert "INTRUSION" not in result

    def test_spam_needs_confirmation_uses_confirmation_title(self, context):
        """With is_low_confidence_not_spam=False, uses needs_confirmation_title."""
        result = format_admin_notification_message(
            context,
            all_admins_delete=False,
            reason="Spam detected",
            lang="en",
        )
        assert "Confirm" in result

    def test_deleted_spam_uses_deleted_title(self, context):
        """With all_admins_delete=True, uses deleted_title (informational)."""
        result = format_admin_notification_message(
            context,
            all_admins_delete=True,
            reason="Spam detected",
            lang="en",
        )
        assert "Spam removed" in result
        assert "Confirm" not in result

    def test_include_mode_tip_false_omits_mode_tip(self, context):
        """With include_mode_tip=False, mode tip is not shown (admin already in delete mode)."""
        result = format_admin_notification_message(
            context,
            all_admins_delete=False,
            reason="Spam detected",
            lang="en",
            include_mode_tip=False,
        )
        assert "Confirm" in result
        assert "Use /mode" not in result
        assert "automatic spam deletion" not in result


class TestFormatAdminNotificationMessage:
    """Test format_admin_notification_message with is_low_confidence_not_spam."""

    @pytest.fixture
    def notification_context(self):
        """Create a minimal MessageNotificationContext for testing."""
        return MessageNotificationContext(
            effective_user_id=67890,
            content_text="Test message",
            chat_title="Test Group",
            chat_username="testgroup",
            is_channel_sender=False,
            violator_name="Test User",
            violator_username="testuser",
            forward_source="",
            message_link="https://t.me/c/123/456",
            entity_name="Test User",
            entity_type="user",
            entity_username="testuser",
        )

    def test_low_confidence_not_spam_uses_review_title(self, notification_context):
        """With is_low_confidence_not_spam=True, uses review title and confidence hint."""
        result = format_admin_notification_message(
            notification_context,
            all_admins_delete=False,
            reason="AI uncertain",
            lang="en",
            is_low_confidence_not_spam=True,
            confidence=10,
        )
        assert "Low confidence" in result
        assert "10" in result
        assert "INTRUSION" not in result

    def test_normal_spam_uses_intrusion_title(self, notification_context):
        """With is_low_confidence_not_spam=False, uses default INTRUSION title."""
        result = format_admin_notification_message(
            notification_context,
            all_admins_delete=False,
            reason="Spam detected",
            lang="en",
            is_low_confidence_not_spam=False,
        )
        assert "Confirm" in result


class TestFormatAdminNotificationMessage:
    """Test format_admin_notification_message with is_low_confidence_not_spam."""

    @pytest.fixture
    def notification_context(self):
        """Create a minimal MessageNotificationContext for testing."""
        return MessageNotificationContext(
            effective_user_id=67890,
            content_text="Test message",
            chat_title="Test Group",
            chat_username="testgroup",
            is_channel_sender=False,
            violator_name="Test User",
            violator_username="testuser",
            forward_source="",
            message_link="https://t.me/c/123/456",
            entity_name="Test User",
            entity_type="group",
            entity_username="testuser",
        )

    def test_low_confidence_not_spam_uses_review_title(self, notification_context):
        """With is_low_confidence_not_spam=True, uses review_low_confidence_title."""
        result = format_admin_notification_message(
            notification_context,
            all_admins_delete=False,
            reason="AI uncertain",
            lang="en",
            is_low_confidence_not_spam=True,
            confidence=10,
        )
        assert "Low confidence" in result
        assert "10" in result
        assert "INTRUSION" not in result

    def test_low_confidence_not_spam_without_confidence_still_works(
        self, notification_context
    ):
        """With is_low_confidence_not_spam=True but confidence=None, no hint."""
        result = format_admin_notification_message(
            notification_context,
            all_admins_delete=False,
            reason="AI uncertain",
            lang="en",
            is_low_confidence_not_spam=True,
            confidence=None,
        )
        assert "Low confidence" in result
        assert "INTRUSION" not in result


class TestFormatAdminNotificationMessage:
    """Test format_admin_notification_message with is_low_confidence_not_spam."""

    @pytest.fixture
    def notification_context(self):
        """Create a minimal MessageNotificationContext for testing."""
        return MessageNotificationContext(
            effective_user_id=67890,
            content_text="Test message",
            chat_title="Test Group",
            chat_username="testgroup",
            is_channel_sender=False,
            violator_name="Test User",
            violator_username="testuser",
            forward_source="",
            message_link="https://t.me/c/123/456",
            entity_name="Test User",
            entity_type="the group",
            entity_username="testuser",
        )

    def test_low_confidence_not_spam_uses_review_title(self, notification_context):
        """With is_low_confidence_not_spam=True, uses review title and hint."""
        result = format_admin_notification_message(
            notification_context,
            all_admins_delete=False,
            reason="AI uncertain",
            lang="en",
            is_low_confidence_not_spam=True,
            confidence=10,
        )

        assert "Low confidence" in result
        assert "10" in result
        assert "INTRUSION" not in result

    def test_low_confidence_not_spam_without_confidence_no_hint(
        self, notification_context
    ):
        """With is_low_confidence_not_spam=True but confidence=None, hint is empty."""
        result = format_admin_notification_message(
            notification_context,
            all_admins_delete=False,
            reason="AI uncertain",
            lang="en",
            is_low_confidence_not_spam=True,
            confidence=None,
        )

        assert "Low confidence" in result
        assert "INTRUSION" not in result

    def test_default_uses_intrusion_title(self, notification_context):
        """With is_low_confidence_not_spam=False, uses standard INTRUSION title."""
        result = format_admin_notification_message(
            notification_context,
            all_admins_delete=False,
            reason="Spam detected",
            lang="en",
        )

        assert "Confirm" in result
        assert "Low confidence" not in result


class TestFormatAdminNotificationMessage:
    """Test format_admin_notification_message with is_low_confidence_not_spam."""

    @pytest.fixture
    def notification_context(self):
        """Create a minimal MessageNotificationContext for testing."""
        return MessageNotificationContext(
            effective_user_id=67890,
            content_text="Test message content",
            chat_title="Test Group",
            chat_username="testgroup",
            is_channel_sender=False,
            violator_name="Test User",
            violator_username="testuser",
            forward_source="",
            message_link="https://t.me/c/123/456",
            entity_name="Test User",
            entity_type="user",
            entity_username="testuser",
        )

    def test_low_confidence_not_spam_uses_review_title(self, notification_context):
        """With is_low_confidence_not_spam=True, uses review_low_confidence_title."""
        result = format_admin_notification_message(
            notification_context,
            all_admins_delete=False,
            reason="Some reason",
            lang="en",
            is_low_confidence_not_spam=True,
            confidence=10,
        )
        assert "Low confidence" in result or "please review" in result.lower()
        assert "10" in result
        assert "INTRUSION" not in result

    def test_default_uses_intrusion_title(self, notification_context):
        """With is_low_confidence_not_spam=False, uses notify_title (INTRUSION)."""
        result = format_admin_notification_message(
            notification_context,
            all_admins_delete=False,
            reason="Some reason",
            lang="en",
        )
        assert "Confirm" in result


class TestFormatAdminNotificationMessage:
    """Test format_admin_notification_message with low-confidence not-spam."""

    def test_low_confidence_not_spam_uses_review_title(self):
        """With is_low_confidence_not_spam=True, uses review_low_confidence_title."""
        context = MessageNotificationContext(
            effective_user_id=123,
            content_text="Test message",
            chat_title="Test Group",
            chat_username="testgroup",
            is_channel_sender=False,
            violator_name="John",
            violator_username="john",
            forward_source="",
            message_link="",
            entity_name="John",
            entity_type="user",
            entity_username="john",
        )
        result = format_admin_notification_message(
            context,
            all_admins_delete=False,
            reason="AI uncertain",
            lang="en",
            is_low_confidence_not_spam=True,
            confidence=10,
        )
        assert "Low confidence" in result
        assert "10" in result
        assert "INTRUSION" not in result

    def test_regular_spam_uses_intrusion_title(self):
        """With is_low_confidence_not_spam=False, uses notify_title (INTRUSION)."""
        context = MessageNotificationContext(
            effective_user_id=123,
            content_text="Test message",
            chat_title="Test Group",
            chat_username="testgroup",
            is_channel_sender=False,
            violator_name="John",
            violator_username="john",
            forward_source="",
            message_link="",
            entity_name="John",
            entity_type="user",
            entity_username="john",
        )
        result = format_admin_notification_message(
            context,
            all_admins_delete=False,
            reason="Spam detected",
            lang="en",
            is_low_confidence_not_spam=False,
        )
        assert "Confirm" in result


class TestFormatAdminNotificationMessage:
    """Test format_admin_notification_message with is_low_confidence_not_spam."""

    def test_low_confidence_not_spam_uses_review_title_and_hint(self):
        """When is_low_confidence_not_spam=True, uses review title and confidence hint."""
        context = MessageNotificationContext(
            effective_user_id=123,
            content_text="Test message",
            chat_title="Test Group",
            chat_username=None,
            is_channel_sender=False,
            violator_name="User",
            violator_username=None,
            forward_source="",
            message_link="",
            entity_name="User",
            entity_type="user",
            entity_username=None,
        )
        result = format_admin_notification_message(
            context,
            all_admins_delete=False,
            reason="AI reason",
            lang="en",
            is_low_confidence_not_spam=True,
            confidence=10,
        )
        assert "Low confidence" in result
        assert "10" in result
        assert "INTRUSION" not in result

    def test_default_spam_uses_needs_confirmation_title(self):
        """When is_low_confidence_not_spam=False, uses needs_confirmation_title."""
        context = MessageNotificationContext(
            effective_user_id=123,
            content_text="Test message",
            chat_title="Test Group",
            chat_username=None,
            is_channel_sender=False,
            violator_name="User",
            violator_username=None,
            forward_source="",
            message_link="",
            entity_name="User",
            entity_type="user",
            entity_username=None,
        )
        result = format_admin_notification_message(
            context,
            all_admins_delete=False,
            reason="AI reason",
            lang="en",
        )
        assert "Confirm" in result
