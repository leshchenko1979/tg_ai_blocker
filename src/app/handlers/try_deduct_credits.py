"""
Модуль для управления кредитами и деактивацией групп.

Содержит функции для:
- Списания кредитов с администраторов групп
- Деактивации модерации при недостатке кредитов
- Уведомления администраторов о деактивации
- Поиска администраторов с минимальным количеством кредитов
"""

import logging
from typing import Optional, Sequence, Tuple, Union

from aiogram.types import ChatMember, ChatMemberAdministrator, ChatMemberOwner

from ..common.bot import bot
from ..common.mp import mp
from ..common.tracking import track_credits_deduction
from ..common.utils import retry_on_network_error
from ..database import deduct_credits_from_admins, get_admin, set_group_moderation

logger = logging.getLogger(__name__)


async def try_deduct_credits(chat_id: int, amount: int, reason: str) -> bool:
    """
    Попытка списать звезды у админов. При неудаче отключает модерацию.

    Args:
        chat_id: ID чата
        amount: Количество списываемых звезд
        reason: Причина списания

    Returns:
        bool: True если списание успешно, False иначе
    """
    if amount == 0:
        return True

    admin_id = await deduct_credits_from_admins(chat_id, amount)
    await track_credits_deduction(chat_id, amount, reason, admin_id)

    if not admin_id:
        logger.warning(f"No paying admins in chat {chat_id} for {reason}")
        await handle_deactivation(chat_id)
        return False

    return True


async def handle_deactivation(chat_id: int) -> None:
    """
    Обрабатывает деактивацию группы.

    Args:
        chat_id: ID чата
    """
    await set_group_moderation(chat_id, False)
    chat = await bot.get_chat(chat_id)
    if not chat.title:
        logger.warning(f"Failed to get chat title for {chat_id}")
        return

    admins = await bot.get_chat_administrators(chat_id)
    min_credits_admin, min_credits = await find_min_credits_admin(admins)

    if min_credits_admin:
        bot_info = await bot.me()
        ref_link = f"https://t.me/{bot_info.username}?start={min_credits_admin.user.id}"

        await send_group_deactivation_message(
            chat_id, ref_link, min_credits_admin, min_credits
        )
        await notify_admins_about_deactivation(admins, chat.title, ref_link)


async def find_min_credits_admin(
    admins: Sequence[ChatMember],
) -> Tuple[Optional[Union[ChatMemberAdministrator, ChatMemberOwner]], float]:
    """
    Находит администратора с наименьшим количеством звезд.

    Args:
        admins: Список администраторов

    Returns:
        Tuple[Optional[Union[ChatMemberAdministrator, ChatMemberOwner]], float]:
            Админ с минимальным балансом и его баланс
    """
    min_credits_admin = None
    min_credits = float("inf")

    for admin in admins:
        if not isinstance(admin, (ChatMemberAdministrator, ChatMemberOwner)):
            continue
        if admin.user.is_bot:
            continue
        admin_data = await get_admin(admin.user.id)
        if admin_data and admin_data.credits < min_credits:
            min_credits = admin_data.credits
            min_credits_admin = admin

    return min_credits_admin, min_credits


async def send_group_deactivation_message(
    chat_id: int,
    ref_link: str,
    min_credits_admin: Union[ChatMemberAdministrator, ChatMemberOwner],
    min_credits: float,
) -> None:
    """
    Отправляет сообщение о деактивации в группу.

    Args:
        chat_id: ID чата
        ref_link: Реферальная ссылка
        min_credits_admin: Админ с минимальным балансом
        min_credits: Минимальный баланс
    """
    message_text = (
        "⚠️ <b>Внимание! Защита группы деактивирована</b>\n\n"
        "Нейромодератор приостановил работу из-за нехватки звезд.\n"
        "Группа осталась без защиты от:\n"
        "• Спама и рекламы\n"
        "• Мошенников\n"
        "• Нежелательных сообщений\n\n"
        "👉 Администраторы могут восстановить защиту через личные сообщения с ботом\n\n"
        f'🤖 <a href="{ref_link}">Хотите такого же модератора в свою группу? Подключить</a>\n'
        '📢 <a href="https://t.me/ai_antispam">Следите за обновлениями в канале проекта</a>'
    )

    try:

        @retry_on_network_error
        async def send_deactivation_message():
            return await bot.send_message(
                chat_id,
                message_text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )

        await send_deactivation_message()

        # Трекинг отправки рекламного сообщения
        mp.track(
            min_credits_admin.user.id,
            "promo_message_sent",
            {
                "type": "no_credits_group",
                "chat_id": chat_id,
                "admin_credits": min_credits,
            },
        )
    except Exception as e:
        logger.warning(f"Failed to send group promo message: {e}", exc_info=True)


async def notify_admins_about_deactivation(
    admins: Sequence[ChatMember], chat_title: str, ref_link: str
) -> None:
    """
    Отправляет персональные уведомления администраторам о деактивации.

    Args:
        admins: Список администраторов
        chat_title: Название чата
        ref_link: Реферальная ссылка
    """
    for admin in admins:
        if not isinstance(admin, (ChatMemberAdministrator, ChatMemberOwner)):
            continue
        if admin.user.is_bot:
            continue

        admin_id = admin.user.id
        message_text = (
            "Внимание, органическая форма жизни!\n\n"
            f'Моя защита группы "{chat_title}" временно приостановлена '
            "из-за истощения звездной энергии.\n\n"
            "Пополни запас звезд командой /buy, чтобы я продолжил охранять "
            "твоё киберпространство от цифровых паразитов!\n\n"
            f"Или пригласи других администраторов: {ref_link}"
        )

        try:

            @retry_on_network_error
            async def send_notification():
                return await bot.send_message(
                    admin_id,
                    message_text,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )

            await send_notification()
        except Exception as e:
            logger.warning(f"Failed to notify admin {admin_id}: {e}", exc_info=True)
