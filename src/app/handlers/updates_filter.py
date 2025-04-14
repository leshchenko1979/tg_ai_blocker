from aiogram import F
from aiogram.filters import and_f, or_f

# Сообщение должно уходить в обработку handle_message, если:
filter_handle_message = and_f(
    F.chat.type.in_(["group", "supergroup"]),
    ~F.from_user.is_bot,
    ~F.from_user.is_admin,
    or_f(
        ~F.reply_to_message,
        and_f(F.reply_to_message, ~F.reply_to_message.message_thread_id),
    ),
    ~F.edited_message,
    ~F.via_bot,
    # Исключаем все типы сервисных сообщений
    ~F.new_chat_member,
    ~F.new_chat_members,
    ~F.left_chat_member,
    ~F.new_chat_title,
    ~F.new_chat_photo,
    ~F.delete_chat_photo,
    ~F.group_chat_created,
    ~F.supergroup_chat_created,
    ~F.channel_chat_created,
    ~F.message_auto_delete_timer_changed,
    ~F.pinned_message,
    # Проверяем наличие текста или медиа-контента
    or_f(
        F.text,
        F.photo,
        F.video,
        F.document,
        F.sticker,
        F.voice,
        F.video_note,
        F.animation,
        F.audio,
        F.story,
    ),
)
