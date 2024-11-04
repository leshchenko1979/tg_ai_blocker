from aiogram import F
from aiogram.filters import or_f, and_f


# Сообщение должно уходить в обработку handle_message, если:
filter_handle_message = and_f(
    F.chat.type.in_(["group", "supergroup"]),
    ~F.from_user.is_bot,
    ~F.from_user.is_admin,
    or_f(
        ~F.reply_to_message,
        and_f(F.reply_to_message, ~F.reply_to_message.message_thread_id),
    ),
    ~F.forward_from,
    ~F.forward_from_chat,
    ~F.forward_from_message_id,
    ~F.edited_message,
    ~F.via_bot,
    F.text,
)
