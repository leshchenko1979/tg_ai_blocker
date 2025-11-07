from aiogram import F
from aiogram.filters import and_f, or_f

# Фильтр для передачи сообщения в handle_message:
# 1. Только для групп и супергрупп
# 2. Только если отправитель не админ
# 3. Сообщение не отредактировано
# 4. Не сервисное сообщение (новые участники, смена фото и т.д.)
# 5. Сообщение содержит текст или медиа
# 6. Ответы не ограничиваем — дальнейшая фильтрация выполняется в
#    check_skip_channel_bot_message

filter_handle_message = and_f(
    # 1. Только групповые чаты
    F.chat.type.in_(["group", "supergroup"]),
    # 2. Не админ
    ~F.from_user.is_admin,
    # 3. Не отредактированное сообщение
    ~F.edited_message,
    # 4. Не сервисные сообщения
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
    # 5. Содержит текст или медиа
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
