from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from common.database import get_user_credits
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
    patched_db_conn, clean_db, payment_message
):
    """Test basic payment processing with credits addition"""
    async with clean_db.acquire() as conn:
        group_id = -1001234567890
        admin_id = payment_message.from_user.id

        # Create test admin directly in database
        await conn.execute(
            """
            INSERT INTO administrators (admin_id, username, credits)
            VALUES ($1, $2, $3)
        """,
            admin_id,
            "TestAdmin",
            0,
        )

        # Create test group directly in database
        await conn.execute(
            """
            INSERT INTO groups (group_id, title, moderation_enabled)
            VALUES ($1, $2, $3)
        """,
            group_id,
            "Test Group",
            False,
        )

        # Add admin to group
        await conn.execute(
            """
            INSERT INTO group_administrators (group_id, admin_id)
            VALUES ($1, $2)
        """,
            group_id,
            admin_id,
        )

        with patch("handlers.payment_handlers.bot.get_chat") as get_chat_mock:
            get_chat_mock.return_value.title = "Test Group"

            with patch(
                "handlers.payment_handlers.bot.send_message"
            ) as send_message_mock:
                await process_successful_payment(payment_message)

                # Verify credits were added
                user_credits = await get_user_credits(admin_id)
                assert user_credits == 100

                # Verify moderation was enabled
                async with clean_db.acquire() as conn:
                    result = await conn.fetchval(
                        """
                        SELECT moderation_enabled FROM groups WHERE group_id = $1
                    """,
                        group_id,
                    )
                    assert result is True

                # Verify success message was sent
                send_message_mock.assert_called_once()
                success_msg = send_message_mock.call_args[0][1]
                assert "100 звезд" in success_msg


@pytest.mark.asyncio
async def test_process_successful_payment_multiple_groups(
    patched_db_conn, clean_db, payment_message
):
    """Test payment processing with multiple groups"""
    async with clean_db.acquire() as conn:
        admin_id = payment_message.from_user.id
        group_ids = [-1001234567890, -1001234567891]

        # Create admins first
        await conn.execute(
            """
            INSERT INTO administrators (admin_id, username, credits)
            VALUES ($1, $2, $3)
        """,
            admin_id,
            "TestAdmin",
            0,
        )

        # Create test groups directly in database
        for group_id in group_ids:
            await conn.execute(
                """
                INSERT INTO groups (group_id, title, moderation_enabled)
                VALUES ($1, $2, $3)
            """,
                group_id,
                "Test Group",
                False,
            )

            # Add admin to group
            await conn.execute(
                """
                INSERT INTO group_administrators (group_id, admin_id)
                VALUES ($1, $2)
            """,
                group_id,
                admin_id,
            )

        with patch("handlers.payment_handlers.bot.get_chat") as get_chat_mock:
            get_chat_mock.return_value.title = "Test Group"

            with patch(
                "handlers.payment_handlers.bot.send_message"
            ) as send_message_mock:
                await process_successful_payment(payment_message)

                # Verify moderation was enabled for all groups
                for group_id in group_ids:
                    result = await conn.fetchval(
                        """
                        SELECT moderation_enabled FROM groups WHERE group_id = $1
                    """,
                        group_id,
                    )
                    assert result is True


@pytest.mark.asyncio
async def test_process_successful_payment_existing_credits(
    patched_db_conn, clean_db, payment_message
):
    """Test payment processing with existing credits"""
    async with clean_db.acquire() as conn:
        admin_id = payment_message.from_user.id

        # Setup existing credits
        await conn.execute(
            """
            INSERT INTO administrators (admin_id, username, credits)
            VALUES ($1, 'testuser', $2)
            ON CONFLICT (admin_id) DO UPDATE SET credits = $2
        """,
            admin_id,
            50,
        )

        with patch("handlers.payment_handlers.bot.send_message") as send_message_mock:
            await process_successful_payment(payment_message)

            # Verify credits were added to existing amount
            user_credits = await get_user_credits(admin_id)
            assert user_credits == 150  # 50 existing + 100 new


@pytest.mark.asyncio
async def test_process_successful_payment_no_groups(
    patched_db_conn, clean_db, payment_message
):
    """Test payment processing when user has no groups"""
    async with clean_db.acquire() as conn:
        admin_id = payment_message.from_user.id

        with patch("handlers.payment_handlers.bot.send_message") as send_message_mock:
            await process_successful_payment(payment_message)

            # Verify credits were still added
            user_credits = await get_user_credits(admin_id)
            assert user_credits == 100


@pytest.mark.asyncio
async def test_process_successful_payment_zero_amount(
    patched_db_conn, clean_db, payment_message
):
    """Test payment processing with zero amount"""
    async with clean_db.acquire() as conn:
        admin_id = payment_message.from_user.id
        payment_message.successful_payment.total_amount = 0

        with patch("handlers.payment_handlers.bot.send_message") as send_message_mock:
            await process_successful_payment(payment_message)

            # Verify no credits were added
            user_credits = await get_user_credits(admin_id)
            assert user_credits == 0


@pytest.mark.asyncio
async def test_process_successful_payment_error_handling(
    patched_db_conn, clean_db, payment_message
):
    """Test error handling during payment processing"""
    with patch("handlers.payment_handlers.add_credits") as add_credits_mock:
        add_credits_mock.side_effect = Exception("Database error")

        with pytest.raises(Exception) as exc_info:
            await process_successful_payment(payment_message)

        assert "Database error" in str(exc_info.value)
