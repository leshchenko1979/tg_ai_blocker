from aiogram import types

from common.bot import bot
from common.database import ensure_group_exists, get_group, set_group_moderation
from common.dp import dp
from common.mp import mp
from common.yandex_logging import get_yandex_logger, log_function_call

logger = get_yandex_logger(__name__)


@dp.my_chat_member()
@log_function_call(logger)
async def handle_bot_status_update(event: types.ChatMemberUpdated) -> None:
    """
    Обработчик изменения статуса бота в чате
    Срабатывает когда бота добавляют/удаляют из группы или меняют его права
    """
    try:
        # Проверяем, что это группа или супергруппа
        if event.chat.type not in ["group", "supergroup"]:
            return

        # Получаем информацию о новом статусе бота
        new_status = event.new_chat_member.status
        chat_id = event.chat.id

        if new_status in ["administrator", "member"]:
            # Бота добавили в группу или дали права администратора
            logger.info(f"Bot added to group {chat_id} with status {new_status}")

            # Получаем список админов
            admins = await bot.get_chat_administrators(chat_id)
            admin_ids = [admin.user.id for admin in admins if not admin.user.is_bot]

            # Сохраняем группу и список админов
            await ensure_group_exists(chat_id, admin_ids)

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
                        logger.warning(f"Failed to notify admin {admin_id}: {e}")
                        continue

        elif new_status == "left" or new_status == "kicked":
            # Бота удалили из группы или кикнули
            logger.info(f"Bot removed from group {chat_id}")

            # Отключаем модерацию
            await set_group_moderation(chat_id, False)

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
                        logger.warning(f"Failed to notify admin {admin_id}: {e}")
                        continue

    except Exception as e:
        logger.error(f"Error handling bot status update: {e}", exc_info=True)
        mp.track(event.chat.id, "unhandled_exception", {"exception": str(e)})
