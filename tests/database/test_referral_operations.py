import pytest
from common.database.referral_operations import (
    get_referrals,
    get_referrer,
    get_total_earnings,
    save_referral,
)


@pytest.mark.asyncio
async def test_save_referral(patched_db_conn, clean_db):
    """Test saving referral relationship"""
    async with clean_db.acquire() as conn:
        # Create users first
        referrer_id = 111
        referral_id = 222

        await conn.execute(
            """
            INSERT INTO administrators (admin_id, username, credits)
            VALUES ($1, 'referrer', 100), ($2, 'referral', 50)
            """,
            referrer_id,
            referral_id,
        )

        # Save referral relationship
        result = await save_referral(referral_id, referrer_id)
        assert result is True

        # Verify relationship was saved
        saved = await conn.fetchrow(
            "SELECT * FROM referral_links WHERE referral_id = $1", referral_id
        )
        assert saved is not None
        assert saved["referrer_id"] == referrer_id


@pytest.mark.asyncio
async def test_save_referral_duplicate(patched_db_conn, clean_db):
    """Test saving duplicate referral relationship"""
    async with clean_db.acquire() as conn:
        # Create users
        referrer_id = 111
        referral_id = 222

        await conn.execute(
            """
            INSERT INTO administrators (admin_id, username, credits)
            VALUES ($1, 'referrer', 100), ($2, 'referral', 50)
            """,
            referrer_id,
            referral_id,
        )

        # Save first relationship
        await save_referral(referral_id, referrer_id)

        # Try to save duplicate
        result = await save_referral(referral_id, 333)
        assert result is False


@pytest.mark.asyncio
async def test_save_referral_cyclic(patched_db_conn, clean_db):
    """Test preventing cyclic referral relationships"""
    async with clean_db.acquire() as conn:
        # Create users
        user_ids = [111, 222, 333]
        for uid in user_ids:
            await conn.execute("INSERT INTO administrators (admin_id) VALUES ($1)", uid)

        # Create chain: 111 -> 222 -> 333
        await save_referral(222, 111)
        await save_referral(333, 222)

        # Try to create cycle: 333 -> 111
        result = await save_referral(111, 333)
        assert result is False


@pytest.mark.asyncio
async def test_get_referrer(patched_db_conn, clean_db):
    """Test getting referrer ID"""
    async with clean_db.acquire() as conn:
        # Create users and relationship
        referrer_id = 111
        referral_id = 222

        await conn.execute(
            """
            INSERT INTO administrators (admin_id, username, credits)
            VALUES ($1, 'referrer', 100), ($2, 'referral', 50)
            """,
            referrer_id,
            referral_id,
        )

        await save_referral(referral_id, referrer_id)

        # Get referrer
        result = await get_referrer(referral_id)
        assert result == referrer_id


@pytest.mark.asyncio
async def test_get_referrals(patched_db_conn, clean_db):
    """Test getting referrals list with earnings"""
    async with clean_db.acquire() as conn:
        # Create users
        referrer_id = 111
        referral_ids = [222, 333]

        # Add users to administrators
        await conn.execute(
            "INSERT INTO administrators (admin_id) VALUES ($1)", referrer_id
        )
        for rid in referral_ids:
            await conn.execute("INSERT INTO administrators (admin_id) VALUES ($1)", rid)
            await save_referral(rid, referrer_id)

        # Add some transactions
        await conn.execute(
            """
            INSERT INTO transactions (admin_id, amount, type, description)
            VALUES
                ($1, 10, 'referral_commission', 'Referral commission from user 222'),
                ($1, 20, 'referral_commission', 'Referral commission from user 333')
            """,
            referrer_id,
        )

        # Get referrals
        referrals = await get_referrals(referrer_id)

        assert len(referrals) == 2
        assert sum(r["earned_stars"] for r in referrals) == 30


@pytest.mark.asyncio
async def test_get_total_earnings(patched_db_conn, clean_db):
    """Test getting total referral earnings"""
    async with clean_db.acquire() as conn:
        user_id = 111

        # Add user
        await conn.execute("INSERT INTO administrators (admin_id) VALUES ($1)", user_id)

        # Add transactions
        await conn.execute(
            """
            INSERT INTO transactions (admin_id, amount, type, description)
            VALUES
                ($1, 10, 'referral_commission', 'Commission 1'),
                ($1, 20, 'referral_commission', 'Commission 2'),
                ($1, 30, 'purchase', 'Not commission')
            """,
            user_id,
        )

        total = await get_total_earnings(user_id)
        assert total == 30  # Only referral_commission transactions
