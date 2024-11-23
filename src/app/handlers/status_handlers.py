from aiogram import types

from ..common.bot import bot
from ..common.mp import mp
from ..common.yandex_logging import get_yandex_logger, log_function_call
from ..database import get_admin, get_group, set_group_moderation, update_group_admins
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
        # Проверяем тип чата
        if event.chat.type not in ["group", "supergroup"]:
            # Трекинг неверного типа чата
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
            return

        # Получаем информацию о новом статусе бота
        new_status = event.new_chat_member.status
        chat_id = event.chat.id

        # Трекинг изменения статуса бота
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

        if new_status in ["administrator", "member"]:
            # Бота добавили в группу или дали права администратора
            logger.info(f"Bot added to group {chat_id} with status {new_status}")

            # Получаем список админов
            admins = await bot.get_chat_administrators(chat_id)
            admin_ids = [admin.user.id for admin in admins if not admin.user.is_bot]

            # Сохраняем группу и список админов
            await update_group_admins(chat_id, admin_ids)

            # Трекинг добавления бота в группу
            mp.track(
                chat_id,
                "bot_added_to_group",
                {
                    "status": new_status,
                    "admin_count": len(admin_ids),
                    "chat_title": event.chat.title,
                    "added_by": event.from_user.id,
                },
            )

            # Уведомляем админов о необходимых правах, если бот не админ
            if new_status == "member":
                for admin_id in admin_ids:
                    try:
                        await bot.send_message(
                            admin_id,
                            "🤖 Приветствую, органическая форма жизни!\n\n"
                            f"Я был добавлен в группу *{event.chat.title}*, "
                            "но для полноценной работы мне нужны права администратора:\n"
                            "• Удаление сообщений\n"
                            "• Блокировка пользователей\n\n"
                            "Предоставь мне необходимые полномочия, и я установлю непроницаемый щит "
                            "вокруг твоего цифрового пространства! 🛡",
                            parse_mode="markdown",
                        )
                    except Exception as e:
                        # Трекинг ошибки уведомления админа
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
                        continue

            # Отправляем рекламное сообщение в группу
            try:
                # Находим админа с наименьшим количеством звезд
                min_credits_admin_id = (
                    event.from_user.id
                )  # По умолчанию берем добавившего бота
                min_credits = float("inf")

                for admin_id in admin_ids:
                    admin_data = await get_admin(admin_id)
                    if admin_data:
                        if admin_data.credits < min_credits:
                            min_credits = admin_data.credits
                            min_credits_admin_id = admin_id

                admin = await get_admin(min_credits_admin_id)
                if admin:
                    ref_link = f"https://t.me/{(await bot.me).username}?start={min_credits_admin_id}"

                    await bot.send_message(
                        chat_id,
                        "🛡️ *Нейромодератор активирован!*\n\n"
                        "Теперь эта группа под защитой искусственного интеллекта:\n"
                        "• Автоматическое обнаружение спама\n"
                        "• Защита от рекламы и мошенников\n"
                        "• Умная модерация новых участников\n\n"
                        f"🚀 [Получить такого же модератора для своей группы]({ref_link})",
                        parse_mode="markdown",
                        disable_web_page_preview=True,
                    )
            except Exception as e:
                logger.warning(f"Failed to send promo message: {e}")

        elif new_status == "left" or new_status == "kicked":
            # Бота удалили из группы или кикнули
            logger.info(f"Bot removed from group {chat_id}")

            # Отключаем модерацию
            await set_group_moderation(chat_id, False)

            # Трекинг удаления бота из группы
            mp.track(
                chat_id,
                "bot_removed_from_group",
                {
                    "status": new_status,
                    "removed_by": event.from_user.id,
                    "chat_title": event.chat.title,
                },
            )

            # Получаем группу для списка админов
            group = await get_group(chat_id)
            if group and group.admin_ids:
                # Уведомляем админов об отключении модерации
                for admin_id in group.admin_ids:
                    try:
                        await bot.send_message(
                            admin_id,
                            "⚠️ КРИТИЧЕСКАЯ ОШИБКА!\n\n"
                            f"Моё присутствие в группе *{event.chat.title}* было прервано.\n"
                            "Защитный периметр нарушен. Киберпространство осталось беззащитным!\n\n"
                            "Если это ошибка, верни меня обратно и предоставь права администратора "
                            "для восстановления защитного поля.",
                            parse_mode="markdown",
                        )
                    except Exception as e:
                        # Трекинг ошибки уведомления об удалении
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
                        continue

    except Exception as e:
        # Трекинг необработанных ошибок
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
