import asyncpg


async def drop_and_create_database(system_conn: asyncpg.Connection, db_name: str):
    """Drop and recreate the database with specific locale and encoding"""
    try:
        # Terminate all connections to the target database
        await system_conn.execute(
            """
            SELECT pg_terminate_backend(pg_stat_activity.pid)
            FROM pg_stat_activity
            WHERE pg_stat_activity.datname = $1
            AND pid <> pg_backend_pid()
        """,
            db_name,
        )

        # Drop and recreate database with specific locale and encoding using template0
        await system_conn.execute(f"DROP DATABASE IF EXISTS {db_name}")
        await system_conn.execute(
            f"""
            CREATE DATABASE {db_name}
            WITH TEMPLATE template0
            ENCODING 'UTF8'
            LC_COLLATE = 'en_US.UTF-8'
            LC_CTYPE = 'en_US.UTF-8'
        """
        )

        # Check that encoding is set to UTF-8
        encoding = await system_conn.fetchval(
            "SELECT pg_encoding_to_char(encoding) FROM pg_database WHERE datname = $1",
            db_name,
        )
        assert encoding == "UTF8"

    except Exception as e:
        raise Exception(f"Failed to recreate database: {e}")


async def create_schema(conn: asyncpg.Connection):
    """Create tables, indexes and procedures for the database"""
    try:
        # Create tables
        await conn.execute(
            """
            -- Administrators table
            CREATE TABLE IF NOT EXISTS administrators (
                admin_id BIGINT PRIMARY KEY,
                username VARCHAR(255),
                credits INTEGER DEFAULT 0 CHECK (credits >= 0),
                delete_spam BOOLEAN DEFAULT true,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                last_active TIMESTAMP NOT NULL DEFAULT NOW()
            );

            -- Groups table
            CREATE TABLE IF NOT EXISTS groups (
                group_id BIGINT PRIMARY KEY,
                title VARCHAR(255),
                moderation_enabled BOOLEAN DEFAULT true,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                last_active TIMESTAMP NOT NULL DEFAULT NOW()
            );

            -- Group administrators mapping
            CREATE TABLE IF NOT EXISTS group_administrators (
                group_id BIGINT REFERENCES groups(group_id) ON DELETE CASCADE,
                admin_id BIGINT REFERENCES administrators(admin_id) ON DELETE CASCADE,
                PRIMARY KEY (group_id, admin_id)
            );

            -- Approved members
            CREATE TABLE IF NOT EXISTS approved_members (
                group_id BIGINT REFERENCES groups(group_id) ON DELETE CASCADE,
                member_id BIGINT NOT NULL,
                approved_at TIMESTAMP NOT NULL DEFAULT NOW(),
                PRIMARY KEY (group_id, member_id)
            );

            -- Message history
            CREATE TABLE IF NOT EXISTS message_history (
                id SERIAL PRIMARY KEY,
                admin_id BIGINT REFERENCES administrators(admin_id) ON DELETE CASCADE,
                role VARCHAR(50) NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );

            -- Spam examples
            CREATE TABLE IF NOT EXISTS spam_examples (
                id SERIAL PRIMARY KEY,
                admin_id BIGINT REFERENCES administrators(admin_id) ON DELETE CASCADE,
                text TEXT NOT NULL,
                name VARCHAR(255),
                bio TEXT,
                score INTEGER NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );

            -- Transaction history
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                admin_id BIGINT REFERENCES administrators(admin_id) ON DELETE CASCADE,
                amount INTEGER NOT NULL,
                type VARCHAR(50) NOT NULL,
                description TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );

            -- Statistics
            CREATE TABLE IF NOT EXISTS stats (
                group_id BIGINT REFERENCES groups(group_id) ON DELETE CASCADE,
                date DATE NOT NULL,
                processed_messages INTEGER DEFAULT 0,
                deleted_spam INTEGER DEFAULT 0,
                PRIMARY KEY (group_id, date)
            );

            -- Referral links
            CREATE TABLE IF NOT EXISTS referral_links (
                id SERIAL PRIMARY KEY,
                referral_id BIGINT REFERENCES administrators(admin_id) ON DELETE CASCADE,
                referrer_id BIGINT REFERENCES administrators(admin_id) ON DELETE CASCADE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );
        """
        )
    except Exception as e:
        raise Exception(f"Failed to create tables: {e}")

    try:
        # Create indexes
        await conn.execute(
            """
            -- Administrators indexes
            CREATE INDEX IF NOT EXISTS idx_administrators_username ON administrators(username);
            CREATE INDEX IF NOT EXISTS idx_administrators_credits ON administrators(credits);

            -- Groups indexes
            CREATE INDEX IF NOT EXISTS idx_groups_moderation ON groups(moderation_enabled);
            CREATE INDEX IF NOT EXISTS idx_groups_last_active ON groups(last_active);

            -- Message history indexes
            CREATE INDEX IF NOT EXISTS idx_message_history_admin ON message_history(admin_id);
            CREATE INDEX IF NOT EXISTS idx_message_history_created ON message_history(created_at);

            -- Spam examples indexes
            CREATE INDEX IF NOT EXISTS idx_spam_examples_admin ON spam_examples(admin_id);
            CREATE INDEX IF NOT EXISTS idx_spam_examples_text ON spam_examples(text);
            CREATE INDEX IF NOT EXISTS idx_spam_examples_score ON spam_examples(score);

            -- Transaction indexes
            CREATE INDEX IF NOT EXISTS idx_transactions_admin ON transactions(admin_id);
            CREATE INDEX IF NOT EXISTS idx_transactions_type ON transactions(type);
            CREATE INDEX IF NOT EXISTS idx_transactions_created ON transactions(created_at);

            -- Stats indexes
            CREATE INDEX IF NOT EXISTS idx_stats_date ON stats(date);

            -- Referral indexes
            CREATE INDEX IF NOT EXISTS idx_referral_links_referrer ON referral_links(referrer_id);
            CREATE INDEX IF NOT EXISTS idx_referral_links_created ON referral_links(created_at);
        """
        )
    except Exception as e:
        raise Exception(f"Failed to create indexes: {e}")

    await create_procedures(conn)


async def create_procedures(conn: asyncpg.Connection):
    """Create stored procedures for the database"""
    try:
        # Create stored procedures
        await conn.execute(
            """
            -- Update group administrators
            CREATE OR REPLACE PROCEDURE update_group_admins(
                p_group_id BIGINT,
                p_admin_ids BIGINT[],
                p_initial_credits INTEGER
            )
            LANGUAGE plpgsql
            AS $$
            BEGIN
                -- Ensure admins exist in administrators table
                INSERT INTO administrators (admin_id, username, credits, created_at, last_active)
                SELECT
                    admin_id,
                    'unknown',
                    p_initial_credits,
                    NOW(),
                    NOW()
                FROM unnest(p_admin_ids) AS admin_id
                ON CONFLICT (admin_id) DO NOTHING;

                -- Create/update group
                INSERT INTO groups (
                    group_id,
                    moderation_enabled,
                    created_at,
                    last_active
                ) VALUES (
                    p_group_id,
                    TRUE,
                    NOW(),
                    NOW()
                )
                ON CONFLICT (group_id) DO UPDATE SET
                    last_active = NOW();

                -- Update group administrators
                DELETE FROM group_administrators
                WHERE group_id = p_group_id;

                INSERT INTO group_administrators (group_id, admin_id)
                SELECT p_group_id, admin_id
                FROM unnest(p_admin_ids) AS admin_id;
            END;
            $$;

            -- Process successful payment
            CREATE OR REPLACE PROCEDURE process_successful_payment(
                p_admin_id BIGINT,
                p_stars_amount INTEGER,
                p_referral_commission_rate FLOAT
            )
            LANGUAGE plpgsql
            AS $$
            DECLARE
                v_referrer_id BIGINT;
                v_commission INTEGER;
            BEGIN
                -- Add credits to the user
                INSERT INTO administrators (admin_id, credits, created_at, last_active)
                VALUES (p_admin_id, p_stars_amount, NOW(), NOW())
                ON CONFLICT (admin_id) DO UPDATE
                SET credits = administrators.credits + p_stars_amount,
                    last_active = NOW();

                -- Record payment transaction
                INSERT INTO transactions (
                    admin_id,
                    amount,
                    type,
                    description
                ) VALUES (
                    p_admin_id,
                    p_stars_amount,
                    'payment',
                    'Stars purchase'
                );

                -- Enable moderation in all user's groups
                UPDATE groups g
                SET moderation_enabled = true,
                    last_active = NOW()
                FROM group_administrators ga
                WHERE g.group_id = ga.group_id
                AND ga.admin_id = p_admin_id;

                -- Check for referrer and process commission
                SELECT referrer_id INTO v_referrer_id
                FROM referral_links
                WHERE referral_id = p_admin_id;

                IF v_referrer_id IS NOT NULL THEN
                    v_commission := FLOOR(p_stars_amount * p_referral_commission_rate);

                    -- Add commission to referrer
                    UPDATE administrators
                    SET credits = credits + v_commission
                    WHERE admin_id = v_referrer_id;

                    -- Record commission transaction
                    INSERT INTO transactions (
                        admin_id,
                        amount,
                        type,
                        description
                    ) VALUES (
                        v_referrer_id,
                        v_commission,
                        'referral_commission',
                        format('Referral commission from user %s', p_admin_id)
                    );
                END IF;
            END;
            $$;

            -- Save referral link
            CREATE OR REPLACE PROCEDURE save_referral(
                p_referral_id BIGINT,
                p_referrer_id BIGINT,
                INOUT p_success BOOLEAN DEFAULT FALSE
            )
            LANGUAGE plpgsql
            AS $$
            DECLARE
                v_existing_referrer BIGINT;
                v_current_id BIGINT;
                v_depth INTEGER := 0;
                v_max_depth INTEGER := 10;
            BEGIN
                -- Prevent self-referral
                IF p_referral_id = p_referrer_id THEN
                    p_success := FALSE;
                    RETURN;
                END IF;

                -- Check for existing referrer
                SELECT referrer_id INTO v_existing_referrer
                FROM referral_links
                WHERE referral_id = p_referral_id;

                IF v_existing_referrer IS NOT NULL THEN
                    p_success := FALSE;
                    RETURN;
                END IF;

                -- Check for cyclic referral
                v_current_id := p_referrer_id;
                WHILE v_depth < v_max_depth AND v_current_id IS NOT NULL LOOP
                    IF v_current_id = p_referral_id THEN
                        p_success := FALSE;
                        RETURN;
                    END IF;

                    SELECT referrer_id INTO v_current_id
                    FROM referral_links
                    WHERE referral_id = v_current_id;

                    v_depth := v_depth + 1;
                END LOOP;

                -- Save the referral link
                INSERT INTO referral_links (referral_id, referrer_id)
                VALUES (p_referral_id, p_referrer_id);

                p_success := TRUE;
            END;
            $$;
        """
        )
    except Exception as e:
        raise Exception(f"Failed to create stored procedures: {e}")


async def truncate_all_tables(conn: asyncpg.Connection):
    """Truncate all tables in the database"""
    await conn.execute(
        """
        DO $$
        DECLARE
            statements CURSOR FOR
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public';
        BEGIN
            FOR stmt IN statements LOOP
                EXECUTE 'TRUNCATE TABLE ' || quote_ident(stmt.tablename) || ' CASCADE';
            END LOOP;
        END $$;
    """
    )
