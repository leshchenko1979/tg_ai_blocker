from datetime import datetime

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
    except Exception as e:
        raise Exception(f"Failed to recreate database: {e}")


async def create_tables_and_indexes(conn: asyncpg.Connection):
    """Create all tables and indexes"""
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
        """
        )

        # Create stored procedures
        await conn.execute(
            """
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
        """
        )

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
        """
        )
    except Exception as e:
        raise Exception(f"Failed to create tables and indexes: {e}")


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
