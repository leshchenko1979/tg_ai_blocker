import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from ..database.group_operations import cleanup_inaccessible_group, get_pool

logger = logging.getLogger(__name__)


async def notify_admins_with_fallback_and_cleanup(
    bot,
    admin_ids: list[int],
    group_id: int,
    private_message: str,
    group_message_template: str = "{mention}, я не могу отправить ни одному администратору личное сообщение. Пожалуйста, напишите мне в личку, чтобы получать важные уведомления о группе!",
    cleanup_if_group_fails: bool = True,
) -> dict:
    """
    Notifies all admins in private, falls back to group if none are reachable.
    Uses the last accessible admin for the group mention.
    Cleans up group if group message fails.
    Returns a dict with results.
    """
    notified_private = []
    unreachable = []
    last_admin_info = None

    for admin_id in admin_ids:
        try:
            admin_chat = await bot.get_chat(admin_id)
            await bot.send_message(admin_id, private_message)
            notified_private.append(admin_id)
            last_admin_info = admin_chat
        except Exception as e:
            logger.warning(f"Failed to notify admin {admin_id} in private: {e}")
            unreachable.append(admin_id)
            try:
                admin_chat = await bot.get_chat(admin_id)
                last_admin_info = admin_chat
            except Exception:
                pass

    result = {
        "notified_private": notified_private,
        "unreachable": unreachable,
        "group_notified": False,
        "group_cleaned_up": False,
    }

    if notified_private:
        return result

    # No admins reachable in private, send group message
    mention = None
    if last_admin_info:
        if getattr(last_admin_info, "username", None):
            mention = f"@{last_admin_info.username}"
        else:
            mention = f'<a href="tg://user?id={last_admin_info.id}">админ</a>'
    else:
        mention = "админ"

    group_message = group_message_template.format(mention=mention)
    try:
        await bot.send_message(
            group_id,
            group_message,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        result["group_notified"] = True
        return result
    except Exception as group_e:
        logger.warning(f"Failed to send group fallback notification: {group_e}")
        if cleanup_if_group_fails:
            try:
                pool = await get_pool()
                async with pool.acquire() as conn:
                    await cleanup_inaccessible_group(conn, group_id)
                logger.info(
                    f"Group {group_id} and its admins removed due to unreachable admins."
                )
                result["group_cleaned_up"] = True
            except Exception as cleanup_e:
                logger.error(
                    f"Failed to cleanup inaccessible group {group_id}: {cleanup_e}"
                )
        return result
