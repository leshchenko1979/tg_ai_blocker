async def test_process_successful_payment(patched_db_conn, clean_db):
    """Test successful payment processing"""
    async with clean_db.acquire() as conn:
        admin_id = 123
        stars_amount = 100
        referrer_id = 456
        commission_rate = 0.1

        # Add both administrators first
        await conn.execute(
            "INSERT INTO administrators (admin_id, credits) VALUES ($1, 0), ($2, 0)",
            admin_id,
            referrer_id,
        )

        # Add referral link after both admins exist
        await conn.execute(
            "INSERT INTO referral_links (referral_id, referrer_id) VALUES ($1, $2)",
            admin_id,
            referrer_id,
        )

        # Process payment
        await conn.execute(
            "CALL process_successful_payment($1, $2, $3)",
            admin_id,
            stars_amount,
            commission_rate,
        )

        # Verify user credits and transactions
        user_credits = await conn.fetchval(
            "SELECT credits FROM administrators WHERE admin_id = $1 FOR UPDATE",
            admin_id,
        )
        assert user_credits == stars_amount

        payment_tx = await conn.fetchrow(
            "SELECT * FROM transactions WHERE admin_id = $1 AND type = 'payment' FOR UPDATE",
            admin_id,
        )
        assert payment_tx["amount"] == stars_amount

        # Verify referrer commission and transactions
        referrer_credits = await conn.fetchval(
            "SELECT credits FROM administrators WHERE admin_id = $1 FOR UPDATE",
            referrer_id,
        )
        assert referrer_credits == int(stars_amount * commission_rate)

        commission_tx = await conn.fetchrow(
            "SELECT * FROM transactions WHERE admin_id = $1 AND type = 'referral_commission' FOR UPDATE",
            referrer_id,
        )
        assert commission_tx["amount"] == int(stars_amount * commission_rate)
