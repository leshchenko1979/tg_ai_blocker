import asyncio
import logging
import pathlib
from collections.abc import Coroutine
from datetime import timedelta
from typing import Any, Dict, List, cast

from aiogram import F, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import or_f

from ..common.bot import bot
from ..spam.user_profile import collect_user_context
from ..common.llms import get_llm_response_with_fallback
from ..common.utils import sanitize_llm_html
from ..database import (
    add_spam_example,
    find_message_by_text_and_user,
    get_admin,
    get_message_history,
    get_spam_examples,
    initialize_new_admin,
    remove_member_from_group,
    save_message,
    update_admin_username_if_needed,
)
from ..database.group_operations import get_admin_groups
from ..i18n import normalize_lang, t
from ..types import ContextStatus
from .dp import dp

logger = logging.getLogger(__name__)


class OriginalMessageExtractionError(Exception):
    """Raised when original message information cannot be extracted"""


@dp.message(
    F.chat.type == "private",
    ~F.text.startswith("/"),
    ~F.forward_from,
    ~F.forward_origin,
)
async def handle_private_message(message: types.Message) -> str:
    """Reply to user in private chat using LLM and message history context."""
    if not message.from_user:
        return "private_no_user_info"

    user = cast("types.User", message.from_user)
    admin_id = user.id
    admin_message = message.text

    if not admin_message:
        return "private_no_message_text"

    await initialize_new_admin(admin_id)
    await update_admin_username_if_needed(admin_id, user.username)

    # Save user message to history
    await save_message(admin_id, "user", admin_message)

    try:
        # Get conversation history
        message_history = await get_message_history(admin_id)

        prd_text = pathlib.Path("PRD.md").read_text()
        spam_examples = await get_spam_examples()

        # Format spam examples for prompt
        formatted_examples = []
        for example in spam_examples:
            example_str = f"<пример>\n<запрос>\n<текст сообщения>\n{example['text']}\n</текст сообщения>"
            if "name" in example:
                example_str += f"\n<имя>{example['name']}</имя>"
            if "bio" in example:
                example_str += f"\n<биография>{example['bio']}</биография>"
            if example.get("linked_channel_fragment"):
                example_str += f"\n<канал>{example['linked_channel_fragment']}</канал>"
            example_str += "\n</запрос>\n<ответ>\n"
            example_str += f"{'да' if example['score'] > 50 else 'нет'} {abs(example['score'])}%\n</ответ>"
            example_str += "\n</пример>"
            formatted_examples.append(example_str)

        system_prompt = f"""
Ты - нейромодератор, киберсущность, защищающая пользователя от спама.

<функционал и стиль ответа>
{prd_text}
</функционал и стиль ответа>

А вот примеры того, что ты считаешь спамом, а что нет
(если spam_score > 50, то сообщение считается спамом):
<примеры>
{"\n".join(formatted_examples)}
</примеры>

Отвечай от имени бота и используй указанный стиль ответа.

Учитывай предыдущий контекст разговора при ответе.

Разбивай текст на короткие абзацы. Умеренно используй эмодзи.
Используй выделение жирным.

<требования к форматированию>
ВНИМАНИЕ! Используй только следующий синтаксис форматирования (Telegram HTML):

<b>Жирный</b>: выделяй жирное тегами <b> и </b>: <b>пример жирного текста</b>
<i>Курсив</i>: выделяй курсив тегами <i> и </i>: <i>пример курсива</i>
Не используй Markdown символы (*, _, `, [, ], etc.)
Не используй другие виды форматирования.

Примеры:
• Это <b>жирный текст</b>
• Это <i>курсив</i>
• Это обычный текст

Неправильно:
• *жирный* (не будет работать)
• _курсив_ (не будет работать)
• **жирный** (не будет работать)

ВСЕГДА следуй этим правилам форматирования!
</требования к форматированию>
"""

        # Combine system prompt with message history
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(message_history)

        # Get response from LLM with retry logic for HTML parsing errors
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            # Get response from LLM
            response = await get_llm_response_with_fallback(messages, temperature=0.6)

            # Save bot's response to history
            await save_message(admin_id, "assistant", response)

            # Send with HTML formatting
            sanitized_response = sanitize_llm_html(response)

            try:
                await message.reply(sanitized_response, parse_mode="HTML")
                return "private_message_replied"

            except TelegramBadRequest as send_error:
                # Check if this is a Telegram HTML parsing error
                error_msg = str(send_error).lower()
                is_html_error = (
                    "can't parse entities" in error_msg
                    or "can't find end tag" in error_msg
                    or "unclosed tag" in error_msg
                )

                if is_html_error and retry_count < max_retries - 1:
                    # This is an HTML parsing error, retry with new LLM response
                    retry_count += 1

                    # Add a note to the conversation history about the HTML formatting issue
                    messages.append({"role": "assistant", "content": response})
                    messages.append(
                        {
                            "role": "user",
                            "content": "Предыдущий ответ содержал ошибку форматирования HTML. Пожалуйста, повтори ответ, строго следуя правилам HTML: используй только <b> для жирного и <i> для курсива, обязательно закрывай все теги.",
                        }
                    )
                    continue  # Retry with updated context
                else:
                    # Not an HTML error or max retries reached, re-raise
                    raise send_error

        # If we get here, max retries exceeded
        raise Exception(
            f"Failed to send message after {max_retries} retries due to HTML parsing errors"
        )

    except Exception as e:
        logger.error(f"Error in private message handler: {e}", exc_info=True)
        raise


@dp.message(F.chat.type == "private", or_f(F.forward_from, F.forward_origin))
async def handle_forwarded_message(message: types.Message) -> str:
    """Prompt admin to confirm spam/not_spam for forwarded message."""
    if not message.from_user:
        return "private_forward_no_user_info"

    admin_id = cast("types.User", message.from_user).id
    await initialize_new_admin(admin_id)
    admin = await get_admin(admin_id)
    lang = (
        normalize_lang(admin.language_code) if admin and admin.language_code else "en"
    )

    row = [
        types.InlineKeyboardButton(
            text=t(lang, "private.spam_button"),
            callback_data="spam_example:spam",
            style="danger",
        ),
        types.InlineKeyboardButton(
            text=t(lang, "private.not_spam_button"),
            callback_data="spam_example:not_spam",
            style="success",
        ),
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[row])

    await message.reply(
        t(lang, "private.add_example_confirm"),
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    return "private_forward_prompt_sent"


@dp.callback_query(F.data.startswith("spam_example:"))
async def process_spam_example_callback(callback: types.CallbackQuery) -> str:
    """Handle spam/not_spam button press for forwarded message."""
    if not callback.from_user or not callback.data or not callback.message:
        return "spam_example_invalid_callback"

    user = cast("types.User", callback.from_user)
    admin_id = user.id
    _, action = callback.data.split(":")

    try:
        if not isinstance(callback.message, types.Message):
            return "spam_example_invalid_message_type"

        info = await extract_original_message_info(callback.message, admin_id)

        channel_fragment = None
        user_id = info.get("user_id")
        username = info.get("username")
        if user_id:
            try:
                user_context = await collect_user_context(user_id, username=username)
            except Exception as exc:  # noqa: BLE001 - log and continue
                logger.info(
                    "Failed to load user context for forwarded user",
                    extra={"user_id": user_id, "username": username, "error": str(exc)},
                )
                user_context = None
            linked = user_context.linked_channel if user_context else None
            channel_fragment = linked.get_fragment() if linked else None

        admin = await get_admin(admin_id)
        lang = (
            normalize_lang(admin.language_code)
            if admin and admin.language_code
            else "en"
        )

        answer_text = (
            t(lang, "private.example_spam_removed")
            if action == "spam"
            else t(lang, "private.example_not_spam_added")
        )
        try:
            await callback.answer(answer_text)
        except Exception:
            pass

        edit_type = "спама" if action == "spam" else "ценного сообщения"
        if lang == "en":
            edit_type = "spam" if action == "spam" else "valuable"

        tasks: List[Coroutine[Any, Any, Any]] = [
            add_spam_example(
                info["text"],
                name=info["name"],
                bio=info["bio"],
                score=100 if action == "spam" else -100,
                admin_id=admin_id,
                linked_channel_fragment=channel_fragment,
                stories_context=info.get("stories_context"),
                reply_context=info.get("reply_context"),
                account_age_context=info.get("account_age_context"),
            ),
            bot.edit_message_text(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                text=t(lang, "private.example_added", type=edit_type),
                parse_mode="HTML",
            ),
        ]

        if action == "spam":
            if info.get("user_id"):
                tasks.append(remove_member_from_group(member_id=info["user_id"]))
            else:
                logger.warning("User ID not found in info, skipping removal from group")

            if info.get("group_chat_id") and info.get("group_message_id"):
                logger.info(
                    f"Adding message deletion task: chat_id={info['group_chat_id']}, message_id={info['group_message_id']}",
                    extra={"message_deletion": "task_added"},
                )
                tasks.append(
                    bot.delete_message(
                        chat_id=info["group_chat_id"],
                        message_id=info["group_message_id"],
                    )
                )
            else:
                logger.warning(
                    "Group chat ID or message ID not found in info, skipping message deletion",
                    extra={
                        "message_deletion": "skipped",
                        "group_chat_id": info.get("group_chat_id"),
                        "group_message_id": info.get("group_message_id"),
                    },
                )

        await asyncio.gather(*tasks)

        if action == "spam":
            logger.info(
                f"Spam example processing completed: user_removed={bool(info.get('user_id'))}, message_deleted={bool(info.get('group_chat_id') and info.get('group_message_id'))}",
                extra={"spam_example_processing": "completed"},
            )

        return "spam_example_processed"

    except OriginalMessageExtractionError as e:
        logger.error(f"Failed to extract original message info: {e}")
        admin = await get_admin(admin_id)
        lang = (
            normalize_lang(admin.language_code)
            if admin and admin.language_code
            else "en"
        )
        await callback.answer(t(lang, "private.error_forward_info"), show_alert=True)
        return "spam_example_extraction_error"
    except Exception as e:
        logger.error(f"Error processing spam example: {e}", exc_info=True)
        admin = await get_admin(admin_id)
        lang = (
            normalize_lang(admin.language_code)
            if admin and admin.language_code
            else "en"
        )
        await callback.answer(t(lang, "private.error_generic"), show_alert=True)
        return "spam_example_error"


async def extract_original_message_info(
    callback_message: types.Message,
    admin_id: int,
) -> Dict[str, Any]:
    """Extract original message info from forwarded message for spam example creation."""
    if not callback_message.reply_to_message:
        raise OriginalMessageExtractionError("No reply_to_message found")

    original_message = callback_message.reply_to_message
    if not original_message.forward_from and not original_message.forward_origin:
        raise OriginalMessageExtractionError("No forward information found")

    info: Dict[str, Any] = {
        "text": original_message.text or original_message.caption or "[MEDIA_MESSAGE]",
        "name": None,
        "bio": None,
        "user_id": None,
        "username": None,
        "group_chat_id": None,
        "group_message_id": None,
        "stories_context": None,
        "reply_context": None,
        "account_age_context": None,
    }

    origin = original_message.forward_origin

    if original_message.forward_from:
        user = original_message.forward_from
        info["name"] = user.full_name
        info["user_id"] = user.id
        info["username"] = user.username
        user_info = await bot.get_chat(user.id)
        info["bio"] = user_info.bio if user_info else None

    if isinstance(origin, types.MessageOriginUser):
        sender_user = origin.sender_user
        info["name"] = info["name"] or sender_user.full_name
        info["user_id"] = sender_user.id
        info["username"] = info["username"] or sender_user.username
        if not info["bio"]:
            user_info = await bot.get_chat(sender_user.id)
            info["bio"] = user_info.bio if user_info else None
    elif isinstance(origin, types.MessageOriginChannel):
        info["name"] = info["name"] or origin.chat.title
        info["group_chat_id"] = origin.chat.id
        info["group_message_id"] = origin.message_id

    if not info["user_id"]:
        logger.info(
            "Cannot determine forwarded user id for spam example",
            extra={
                "forward_from": bool(original_message.forward_from),
                "forward_origin_type": (
                    getattr(origin, "type", None) if origin else None
                ),
            },
        )

    # If we don't have group chat/message IDs from forward metadata, try PostgreSQL lookup
    if not info["group_chat_id"] or not info["group_message_id"]:
        admin_groups = await get_admin_groups(admin_id)
        admin_group_ids = [group["id"] for group in admin_groups]

        if admin_group_ids:
            forward_date = original_message.forward_date or original_message.date
            from_date = forward_date - timedelta(days=3)
            to_date = forward_date + timedelta(days=1)

            lookup_result = await find_message_by_text_and_user(
                message_text=info["text"],
                admin_chat_ids=admin_group_ids,
                from_date=from_date,
                to_date=to_date,
                user_id=info["user_id"],
            )

            if lookup_result:
                info["group_chat_id"] = lookup_result["chat_id"]
                info["group_message_id"] = lookup_result["message_id"]
                if not info["user_id"] and lookup_result.get("user_id"):
                    info["user_id"] = lookup_result["user_id"]
                    logger.info(
                        f"Recovered user_id {info['user_id']} from message_lookup_cache",
                        extra={"message_lookup": "user_recovered"},
                    )
                info["reply_context"] = lookup_result.get("reply_to_text")
                info["stories_context"] = lookup_result.get("stories_context")
                info["account_age_context"] = lookup_result.get("account_age_context")

                # On-demand context when cache has none (e.g. approved user message)
                if info["user_id"] and (
                    not info.get("stories_context")
                    or not info.get("account_age_context")
                ):
                    try:
                        user_context = await collect_user_context(
                            info["user_id"], username=info.get("username")
                        )
                        if user_context.account_age and not info.get(
                            "account_age_context"
                        ):
                            if (
                                user_context.account_age.status == ContextStatus.FOUND
                                and user_context.account_age.content
                            ):
                                info["account_age_context"] = (
                                    user_context.account_age.content.to_prompt_fragment()
                                )
                            elif user_context.account_age.status == ContextStatus.EMPTY:
                                info["account_age_context"] = "[EMPTY]"
                    except Exception as e:
                        logger.debug(
                            "On-demand context collection failed",
                            extra={"user_id": info["user_id"], "error": str(e)},
                        )

                logger.info(
                    "Message lookup succeeded",
                    extra={
                        "message_lookup": "success",
                        "candidate_chats": len(admin_group_ids),
                        "user_id_provided": info["user_id"] is not None,
                    },
                )
            else:
                logger.info(
                    "No matching message found in message_lookup_cache",
                    extra={
                        "message_lookup": "miss",
                        "candidate_chats": len(admin_group_ids),
                        "user_id_provided": info["user_id"] is not None,
                    },
                )
        else:
            logger.info(
                "Admin has no managed groups, skipping message lookup",
                extra={"message_lookup": "skip", "candidate_chats": 0},
            )

    return info
