from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import CallbackQuery, Chat, Message

from ...app.database import get_admin_credits
from ...app.handlers.payment_handlers import (
    handle_buy_command,
    handle_buy_stars_callback,
    process_successful_payment,
)


@pytest.fixture
def payment_message():
    message = MagicMock(spec=Message)
    message.from_user = MagicMock()
    message.from_user.id = 123456
    message.successful_payment = MagicMock()
    message.successful_payment.total_amount = 100
    return message


@pytest.fixture
def callback_query():
    callback = MagicMock(spec=CallbackQuery)
    callback.from_user = MagicMock()
    callback.from_user.id = 123456
    callback.message = MagicMock(spec=Message)
    callback.message.chat = MagicMock(spec=Chat)
    callback.message.chat.id = 123456
    callback.data = "buy_stars:100"
    callback.answer = AsyncMock()
    return callback


@pytest.mark.asyncio
async def test_handle_buy_command(payment_message):
    """Test buy command shows payment menu"""
    # Create a coroutine mock for the reply method
    reply_mock = MagicMock()
    reply_mock.return_value = None  # or whatever your reply method should return
    payment_message.reply = AsyncMock(return_value=reply_mock)

    with patch("src.app.handlers.payment_handlers.mp.track") as track_mock:
        await handle_buy_command(payment_message)

        # Verify tracking was called
        track_mock.assert_called_once_with(
            payment_message.from_user.id, "payment_menu_opened"
        )

        # Verify reply was called with correct keyboard
        payment_message.reply.assert_called_once()
        call_args = payment_message.reply.call_args
        reply_text = call_args[0][0]
        reply_markup = call_args[1]["reply_markup"]

        assert "100 звезд" in reply_text
        assert "500 звезд" in reply_text
        assert "1000 звезд" in reply_text
        assert "5000 звезд" in reply_text
        assert len(reply_markup.inline_keyboard) == 2
        assert len(reply_markup.inline_keyboard[0]) == 2


@pytest.mark.asyncio
async def test_handle_buy_stars_callback(callback_query):
    """Test callback handling for star package selection"""
    callback_query.data = "buy_stars:500"

    with patch("src.app.handlers.payment_handlers.mp.track") as track_mock:
        with patch(
            "src.app.handlers.payment_handlers.bot.send_invoice"
        ) as invoice_mock:
            await handle_buy_stars_callback(callback_query)

            # Verify tracking was called
            track_mock.assert_called_once_with(
                callback_query.from_user.id,
                "payment_package_selected",
                {"stars_amount": 500},
            )

            # Verify invoice was sent with correct amount
            invoice_mock.assert_called_once()
            assert invoice_mock.call_args[1]["prices"][0].amount == 500


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

        with patch("src.app.handlers.payment_handlers.bot.get_chat") as get_chat_mock:
            get_chat_mock.return_value.title = "Test Group"

            with patch(
                "src.app.handlers.payment_handlers.bot.send_message"
            ) as send_message_mock:
                await process_successful_payment(payment_message)

                # Verify credits were added
                user_credits = await get_admin_credits(admin_id)
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

        with patch("src.app.handlers.payment_handlers.bot.get_chat") as get_chat_mock:
            get_chat_mock.return_value.title = "Test Group"

            with patch(
                "src.app.handlers.payment_handlers.bot.send_message"
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

        with patch(
            "src.app.handlers.payment_handlers.bot.send_message"
        ) as send_message_mock:
            await process_successful_payment(payment_message)

            # Verify credits were added to existing amount
            user_credits = await get_admin_credits(admin_id)
            assert user_credits == 150  # 50 existing + 100 new


@pytest.mark.asyncio
async def test_process_successful_payment_no_groups(
    patched_db_conn, clean_db, payment_message
):
    """Test payment processing when user has no groups"""
    async with clean_db.acquire() as conn:
        admin_id = payment_message.from_user.id

        with patch(
            "src.app.handlers.payment_handlers.bot.send_message"
        ) as send_message_mock:
            await process_successful_payment(payment_message)

            # Verify credits were still added
            user_credits = await get_admin_credits(admin_id)
            assert user_credits == 100


@pytest.mark.asyncio
async def test_process_successful_payment_zero_amount(
    patched_db_conn, clean_db, payment_message
):
    """Test payment processing with zero amount"""
    async with clean_db.acquire() as conn:
        admin_id = payment_message.from_user.id
        payment_message.successful_payment.total_amount = 0

        with patch(
            "src.app.handlers.payment_handlers.bot.send_message"
        ) as send_message_mock:
            await process_successful_payment(payment_message)

            # Verify no credits were added
            user_credits = await get_admin_credits(admin_id)
            assert user_credits == 0


@pytest.mark.asyncio
async def test_process_successful_payment_large_amount(
    patched_db_conn, clean_db, payment_message
):
    """Test payment processing with large amount (5000 stars)"""
    payment_message.successful_payment.total_amount = 5000
    async with clean_db.acquire() as conn:
        admin_id = payment_message.from_user.id

        await conn.execute(
            """
            INSERT INTO administrators (admin_id, username, credits)
            VALUES ($1, $2, $3)
        """,
            admin_id,
            "TestAdmin",
            0,
        )

        with patch(
            "src.app.handlers.payment_handlers.bot.send_message"
        ) as send_message_mock:
            await process_successful_payment(payment_message)

            # Verify correct amount of credits were added
            user_credits = await get_admin_credits(admin_id)
            assert user_credits == 5000

            # Verify success message contains correct amount
            send_message_mock.assert_called_once()
            success_msg = send_message_mock.call_args[0][1]
            assert "5000 звезд" in success_msg


@pytest.mark.asyncio
async def test_process_successful_payment_with_referral(
    patched_db_conn, clean_db, payment_message
):
    """Test payment processing with referral commission"""
    async with clean_db.acquire() as conn:
        admin_id = payment_message.from_user.id
        referrer_id = 654321
        payment_message.successful_payment.total_amount = 1000

        # Create referrer and referral in database
        await conn.execute(
            """
            INSERT INTO administrators (admin_id, username, credits)
            VALUES ($1, $2, $3), ($4, $5, $6)
        """,
            admin_id,
            "TestUser",
            0,
            referrer_id,
            "Referrer",
            0,
        )

        # Add referral link
        await conn.execute(
            """
            INSERT INTO referral_links (referrer_id, referral_id)
            VALUES ($1, $2)
        """,
            referrer_id,
            admin_id,
        )

        with patch(
            "src.app.handlers.payment_handlers.bot.send_message"
        ) as send_message_mock:
            await process_successful_payment(payment_message)

            # Verify referrer received commission
            referrer_credits = await get_admin_credits(referrer_id)
            assert referrer_credits == 100  # 10% of 1000

            # Verify referral received full amount
            referral_credits = await get_admin_credits(admin_id)
            assert referral_credits == 1000
