from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from common.database import Group, get_group, get_user_credits, save_group
from handlers.payment_handlers import process_successful_payment


@pytest.fixture(autouse=True)
def mock_logger():
    with patch("handlers.payment_handlers.get_yandex_logger") as mock:
        logger_mock = MagicMock()
        mock.return_value = logger_mock
        yield logger_mock


@pytest.fixture
def payment_message():
    message = MagicMock()
    message.from_user = MagicMock()
    message.from_user.id = 123456
    message.successful_payment = MagicMock()
    message.successful_payment.total_amount = 100

    return message


@pytest.mark.asyncio
async def test_process_successful_payment_basic(
    patched_redis_conn, clean_redis, payment_message
):
    """Test basic payment processing with credits addition"""

    # Setup test data

    group_id = -1001234567890

    admin_id = payment_message.from_user.id

    # Create test group with the admin

    group = Group(group_id=group_id, admin_ids=[admin_id], is_moderation_enabled=False)
    await save_group(group)

    with patch("handlers.payment_handlers.bot.get_chat") as get_chat_mock:
        get_chat_mock.return_value.title = "Test Group"

        with patch("handlers.payment_handlers.bot.send_message") as send_message_mock:
            # Process payment
            await process_successful_payment(payment_message)

            # Verify credits were added

            user_credits = await get_user_credits(admin_id)

            assert int(user_credits) == 100

            # Verify moderation was enabled

            group = await get_group(group_id)

            assert group.is_moderation_enabled

            # Verify success message was sent

            send_message_mock.assert_called_once()

            success_msg = send_message_mock.call_args[0][1]

            assert "100 звезд" in success_msg


@pytest.mark.asyncio
async def test_process_successful_payment_multiple_groups(
    patched_redis_conn, clean_redis, payment_message
):
    """Test payment processing with multiple groups"""

    admin_id = payment_message.from_user.id

    group_ids = [-1001234567890, -1001234567891]

    # Create test groups

    for group_id in group_ids:
        group = Group(
            group_id=group_id, admin_ids=[admin_id], is_moderation_enabled=False
        )
        await save_group(group)

    # Mock bot.get_chat method
    with patch("handlers.payment_handlers.bot.get_chat") as get_chat_mock:
        get_chat_mock.return_value.title = "Test Group"

        with patch("handlers.payment_handlers.bot.send_message") as send_message_mock:
            await process_successful_payment(payment_message)

            # Verify moderation was enabled for all groups

            for group_id in group_ids:
                group = await get_group(group_id)
                assert group.is_moderation_enabled


@pytest.mark.asyncio
async def test_process_successful_payment_existing_credits(
    patched_redis_conn, clean_redis, payment_message
):
    """Test payment processing with existing credits"""

    admin_id = payment_message.from_user.id

    # Setup existing credits

    await clean_redis.hset(f"user:{admin_id}", "credits", "50")

    with patch("handlers.payment_handlers.bot.send_message") as send_message_mock:
        await process_successful_payment(payment_message)

        # Verify credits were added to existing amount

        user_credits = await get_user_credits(admin_id)

        assert int(user_credits) == 150  # 50 existing + 100 new


@pytest.mark.asyncio
async def test_process_successful_payment_no_groups(
    patched_redis_conn, clean_redis, payment_message
):
    """Test payment processing when user has no groups"""

    admin_id = payment_message.from_user.id

    with patch("handlers.payment_handlers.bot.send_message") as send_message_mock:
        await process_successful_payment(payment_message)

        # Verify credits were still added

        user_credits = await get_user_credits(admin_id)

        assert int(user_credits) == 100


@pytest.mark.asyncio
async def test_process_successful_payment_zero_amount(
    patched_redis_conn, clean_redis, payment_message
):
    """Test payment processing with zero amount"""

    admin_id = payment_message.from_user.id

    payment_message.successful_payment.total_amount = 0

    with patch("handlers.payment_handlers.bot.send_message") as send_message_mock:
        await process_successful_payment(payment_message)

        # Verify no credits were added

        user_credits = await get_user_credits(admin_id)

        assert int(user_credits) == 0


@pytest.mark.asyncio
async def test_process_successful_payment_error_handling(
    patched_redis_conn, clean_redis, payment_message
):
    """Test error handling during payment processing"""

    with patch("handlers.payment_handlers.add_credits") as add_credits_mock:
        add_credits_mock.side_effect = Exception("Database error")

        with pytest.raises(Exception) as exc_info:
            await process_successful_payment(payment_message)

        assert "Database error" in str(exc_info.value)
