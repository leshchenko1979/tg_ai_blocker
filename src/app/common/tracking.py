"""
Модуль для отслеживания событий и метрик в приложении.

Содержит функции для:
- Отправки событий в Mixpanel для всех администраторов группы
- Отслеживания списания кредитов
- Отслеживания обнаружения спама
"""

import logging
from typing import Optional

from aiogram.types import ChatMemberAdministrator, ChatMemberOwner

from ..common.bot import bot
from ..common.mp import mp

logger = logging.getLogger(__name__)


async def track_group_event(
    chat_id: int,
    event_name: str,
    event_properties: dict,
) -> None:
    """
    Отправляет событие в Mixpanel всем админам группы.

    Args:
        chat_id: ID группы
        event_name: Название события
        event_properties: Свойства события
    """
    from ..database import get_group

    group = await get_group(chat_id)
    if not group or not group.admin_ids:
        return

    # Добавляем group_id в свойства события, если его еще нет
    if "group_id" not in event_properties:
        event_properties["group_id"] = chat_id

    # Отправляем событие каждому админу
    for admin_id in group.admin_ids:
        mp.track(admin_id, event_name, event_properties)


async def track_credits_deduction(
    chat_id: int,
    amount: int,
    reason: str,
    admin_id: Optional[int] = None,
    success: bool = True,
) -> None:
    """
    Трекинг попытки списания звезд в Mixpanel.

    Args:
        chat_id: ID чата
        amount: Количество списываемых звезд
        reason: Причина списания
        admin_id: ID администратора (если есть)
        success: Успешность списания
    """
    if not admin_id and not success:
        # Получаем любого админа для трекинга неудачного списания
        admins = await bot.get_chat_administrators(chat_id)
        admin = next(
            (
                a
                for a in admins
                if isinstance(a, (ChatMemberAdministrator, ChatMemberOwner)) and not a.user.is_bot
            ),
            None,
        )
        admin_id = admin.user.id if admin else None

    if admin_id:
        mp.track(
            admin_id,
            "credits_deduction_attempt",
            {
                "chat_id": chat_id,
                "amount": amount,
                "reason": reason,
                "success": success,
            },
        )


async def track_spam_detection(message) -> None:
    """
    Трекинг обнаружения спам-сообщения в Mixpanel.

    Args:
        message: Сообщение, определенное как спам
    """
    if not message.from_user:
        return

    await track_group_event(
        message.chat.id,
        "spam_detected",
        {
            "message_id": message.message_id,
            "author_id": message.from_user.id,
            "spammer_username": message.from_user.username,
            "message_text": message.text or message.caption or "[MEDIA_MESSAGE]",
            "group_name": message.chat.title,
        },
    )
