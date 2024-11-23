from aiogram import types

from ..common.bot import bot
from ..common.mp import mp
from ..common.yandex_logging import get_yandex_logger, log_function_call
from ..database import get_admin, get_group, update_group_admins
from .dp import dp

logger = get_yandex_logger(__name__)


@dp.my_chat_member()
@log_function_call(logger)
async def handle_bot_status_update(event: types.ChatMemberUpdated) -> None:
    """
    Обработчик изменения статуса бота в чате
    Срабатывает когда бота добавляют/удаляют из группы или меняют его права
    """
    try:
        if event.chat.type not in ["group", "supergroup"]:
            await _handle_wrong_chat_type(event)
            return

        new_status = event.new_chat_member.status
        chat_id = event.chat.id

        mp.track(
            event.from_user.id,
            "bot_status_changed",
            {
                "chat_id": chat_id,
                "new_status": new_status,
                "old_status": event.old_chat_member.status,
                "chat_type": event.chat.type,
                "chat_title": event.chat.title,
            },
        )

        if new_status in ["administrator", "member", "restricted"]:
            logger.info(f"Bot added to group {chat_id} with status {new_status}")

            admins = await bot.get_chat_administrators(chat_id)
            admin_ids = [admin.user.id for admin in admins if not admin.user.is_bot]
            await update_group_admins(chat_id, admin_ids)

            has_admin_rights = (
                new_status == "administrator"
                and event.new_chat_member.can_delete_messages
                and event.new_chat_member.can_restrict_members
            )

            mp.track(
                chat_id,
                "bot_added_to_group",
                {
                    "status": new_status,
                    "admin_count": len(admin_ids),
                    "chat_title": event.chat.title,
                    "added_by": event.from_user.id,
                    "has_admin_rights": has_admin_rights,
                },
            )

            if not has_admin_rights:
                await _notify_admins_about_rights(
                    chat_id, event.chat.title, event.chat.username, admin_ids
                )

            await _send_promo_message(
                chat_id,
                event.chat.title,
                event.chat.username,
                admin_ids,
                event.from_user.id,
            )

        elif new_status in ["left", "kicked"]:
            logger.info(f"Bot removed from group {chat_id}")

            mp.track(
                chat_id,
                "bot_removed_from_group",
                {
                    "status": new_status,
                    "removed_by": event.from_user.id,
                    "chat_title": event.chat.title,
                },
            )

            group = await get_group(chat_id)
            if group and group.admin_ids:
                await _notify_admins_about_removal(
                    chat_id, event.chat.title, event.chat.username, group.admin_ids
                )

    except Exception as e:
        mp.track(
            event.chat.id,
            "error_bot_status_update",
            {
                "error_type": type(e).__name__,
                "error_message": str(e),
                "new_status": event.new_chat_member.status,
            },
        )
        logger.error(f"Error handling bot status update: {e}", exc_info=True)


async def _handle_wrong_chat_type(event: types.ChatMemberUpdated) -> None:
    """Обработка добавления бота в неподдерживаемый тип чата"""
    mp.track(
        event.from_user.id,
        "bot_status_wrong_chat_type",
        {
            "chat_type": event.chat.type,
            "new_status": event.new_chat_member.status,
        },
    )

    if event.new_chat_member.status == "member":
        try:
            await bot.send_message(
                event.from_user.id,
                "🤖 Внимание! Модерация комментариев работает только в группах.\n\n"
                "Пожалуйста, добавьте бота в группу с комментариями, чтобы запустить модерацию. "
                "При добавлении бота непосредственно в канал модерация работать не будет.",
                parse_mode="markdown",
            )
        except Exception as e:
            logger.warning(f"Failed to send notification about chat type: {e}")


async def _notify_admins_about_rights(
    chat_id: int, chat_title: str, username: str | None, admin_ids: list[int]
) -> None:
    """Уведомление админов о необходимости выдать права боту"""
    for admin_id in admin_ids:
        try:
            await bot.send_message(
                admin_id,
                "🤖 Приветствую, органическая форма жизни!\n\n"
                f"Я был добавлен в группу *{chat_title}*"
                f"{f' (@{username})' if username else ''}, "
                "но для полноценной работы мне нужны права администратора:\n"
                "• Удаление сообщений\n"
                "• Блокировка пользователей\n\n"
                "Предоставь мне необходимые полномочия, и я установлю непроницаемый щит "
                "вокруг твоего цифрового пространства! 🛡",
                parse_mode="markdown",
            )
        except Exception as e:
            mp.track(
                admin_id,
                "error_admin_notification",
                {
                    "chat_id": chat_id,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )
            logger.warning(f"Failed to notify admin {admin_id}: {e}")


async def _send_promo_message(
    chat_id: int,
    chat_title: str,
    username: str | None,
    admin_ids: list[int],
    added_by_id: int,
) -> None:
    """Отправка рекламного сообщения в группу"""
    try:
        min_credits_admin_id = added_by_id
        min_credits = float("inf")

        for admin_id in admin_ids:
            admin_data = await get_admin(admin_id)
            if admin_data and admin_data.credits < min_credits:
                min_credits = admin_data.credits
                min_credits_admin_id = admin_id

        admin = await get_admin(min_credits_admin_id)
        if admin:
            bot_info = await bot.get_me()
            ref_link = f"https://t.me/{bot_info.username}?start={min_credits_admin_id}"

            await bot.send_message(
                chat_id,
                "🛡️ *Нейромодератор активирован!*\n\n"
                f"Группа *{chat_title}*"
                f"{f' (@{username})' if username else ''} "
                "теперь под защитой искусственного интеллекта:\n"
                "• Автоматическое обнаружение спама\n"
                "• Защита от рекламы и мошенников\n"
                "• Умная модерация новых участников\n\n"
                f"🚀 [Получить такого же модератора для своей группы]({ref_link})",
                parse_mode="markdown",
                disable_web_page_preview=True,
            )
    except Exception as e:
        logger.warning(f"Failed to send promo message: {e}")


async def _notify_admins_about_removal(
    chat_id: int, chat_title: str, username: str | None, admin_ids: list[int]
) -> None:
    """Уведомление админов об удалении бота из группы"""
    for admin_id in admin_ids:
        try:
            await bot.send_message(
                admin_id,
                "⚠️ КРИТИЧЕСКАЯ ОШИБКА!\n\n"
                f"Моё присутствие в группе *{chat_title}*"
                f"{f' (@{username})' if username else ''} "
                "было прервано.\n"
                "Защитный периметр нарушен. Киберпространство осталось беззащитным!\n\n"
                "Если это ошибка, верни меня обратно и предоставь права администратора "
                "для восстановления защитного поля.",
                parse_mode="markdown",
            )
        except Exception as e:
            mp.track(
                admin_id,
                "error_removal_notification",
                {
                    "chat_id": chat_id,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )
            logger.warning(f"Failed to notify admin {admin_id}: {e}")
