from typing import Dict, List, Optional

from ..yandex_logging import get_yandex_logger, log_function_call
from .postgres_connection import get_pool

logger = get_yandex_logger(__name__)


@log_function_call(logger)
async def save_referral(user_id: int, referrer_id: int) -> bool:
    """Сохраняет связь реферала с реферером"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            success = await conn.fetchval(
                "CALL save_referral($1, $2, NULL)",
                user_id,
                referrer_id,
            )
            return success
        except Exception as e:
            logger.error(
                f"Error saving referral link: user_id={user_id}, "
                f"referrer_id={referrer_id}, error={str(e)}",
                exc_info=True,
            )
            raise


@log_function_call(logger)
async def get_referrer(user_id: int) -> Optional[int]:
    """Возвращает ID реферера для пользователя"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            return await conn.fetchval(
                "SELECT referrer_id FROM referral_links WHERE referral_id = $1", user_id
            )
        except Exception as e:
            logger.error(
                f"Error getting referrer for user {user_id}: {e}", exc_info=True
            )
            raise


@log_function_call(logger)
async def get_referrals(user_id: int) -> List[Dict]:
    """Возвращает список рефералов пользователя с информацией о заработке"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            referrals = await conn.fetch(
                """
                SELECT
                    rl.referral_id,
                    rl.created_at as joined_at,
                    COALESCE(SUM(t.amount), 0) as earned_stars
                FROM referral_links rl
                LEFT JOIN transactions t ON
                    t.admin_id = $1
                    AND t.type = 'referral_commission'
                    AND t.description LIKE 'Referral commission from user ' || rl.referral_id::text || '%'
                WHERE rl.referrer_id = $1
                GROUP BY rl.referral_id, rl.created_at
                ORDER BY rl.created_at DESC
                """,
                user_id,
            )
            return referrals
        except Exception as e:
            logger.error(
                f"Error getting referrals for user {user_id}: {e}", exc_info=True
            )
            raise


@log_function_call(logger)
async def get_total_earnings(user_id: int) -> int:
    """Возвращает общую сумму заработанных звезд от рефералов"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            total = await conn.fetchval(
                """
                SELECT COALESCE(SUM(amount), 0)
                FROM transactions
                WHERE admin_id = $1 AND type = 'referral_commission'
                """,
                user_id,
            )
            return total
        except Exception as e:
            logger.error(
                f"Error getting total earnings for user {user_id}: {e}", exc_info=True
            )
            raise
