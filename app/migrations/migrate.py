import asyncio
from typing import Any, List

# Load environment variables
from dotenv import load_dotenv

load_dotenv()
from app.common.database import get_pool


async def migrate(conn: Any) -> List[str]:
    """
    Создает таблицы для реферальной системы
    Возвращает список выполненных операций
    """
    operations = []
    print("Starting database migration...")

    # Start transaction
    async with conn.transaction():
        print("Dropping existing stored procedures...")
        # Drop existing stored procedures first
        await conn.execute(
            """
            DO $$
            DECLARE
                proc record;
            BEGIN
                FOR proc IN (SELECT proname, oidvectortypes(proargtypes) as args
                            FROM pg_proc
                            WHERE pronamespace = 'public'::regnamespace)
                LOOP
                    EXECUTE 'DROP PROCEDURE IF EXISTS ' || proc.proname || '(' || proc.args || ') CASCADE';
                END LOOP;
            END $$;
            """
        )
        operations.append("Dropped existing stored procedures")
        print("✓ Dropped existing stored procedures")

        print("Creating referral_links table...")
        # Создаем таблицу для реферальных связей
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS referral_links (
                id SERIAL PRIMARY KEY,
                referral_id BIGINT REFERENCES administrators(admin_id) ON DELETE CASCADE,
                referrer_id BIGINT REFERENCES administrators(admin_id) ON DELETE CASCADE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE(referral_id)
            );
        """
        )
        operations.append("Created table referral_links")
        print("✓ Created referral_links table")

        print("Creating indexes...")
        # Создаем индексы
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_referral_links_referrer
            ON referral_links(referrer_id);

            CREATE INDEX IF NOT EXISTS idx_referral_links_created
            ON referral_links(created_at);
        """
        )
        operations.append("Created referral indexes")
        print("✓ Created indexes")

        print("Creating process_successful_payment procedure...")
        # Add the process_successful_payment stored procedure
        await conn.execute(
            """
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
            """
        )
        operations.append("Created process_successful_payment procedure")
        print("✓ Created process_successful_payment procedure")

        print("Creating save_referral procedure...")
        await conn.execute(
            """
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
        operations.append("Created save_referral procedure")
        print("✓ Created save_referral procedure")

    print(f"Migration completed successfully. {len(operations)} operations performed.")
    return operations


async def main():
    print("Getting database pool...")
    pool = await get_pool()
    print("Migrating database...")
    async with pool.acquire() as conn:
        print("Acquired connection from pool")
        await migrate(conn)


if __name__ == "__main__":
    asyncio.run(main())
