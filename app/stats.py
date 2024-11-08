from datetime import datetime
from typing import Dict

# Статистика для биллинга
stats: Dict[int, Dict[str, int]] = {}


def update_stats(chat_id: int, action: str) -> None:
    """
    Обновляет статистику для биллинга

    Args:
        chat_id (int): ID чата
        action (str): Тип действия ('processed' или 'deleted')
    """
    if chat_id not in stats:
        stats[chat_id] = {
            "processed_messages": 0,
            "deleted_spam": 0,
            "last_update": datetime.now().isoformat(),
        }

    if action == "processed":
        stats[chat_id]["processed_messages"] += 1
    elif action == "deleted":
        stats[chat_id]["deleted_spam"] += 1

    stats[chat_id]["last_update"] = datetime.now().isoformat()
