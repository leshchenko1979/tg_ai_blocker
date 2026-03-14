import asyncio
import logging

from aiogram import F, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from ..common.bot import bot
from ..common.utils import get_add_to_group_url, retry_on_network_error
from ..database import get_admin, get_group, update_admin_language
from ..database.group_operations import add_member
from ..database.spam_examples import (
    confirm_pending_example_as_not_spam,
    confirm_pending_example_as_spam,
)
from ..i18n import resolve_lang, t
from .dp import dp
from .handle_spam import ban_user_for_spam

logger = logging.getLogger(__name__)


@dp.callback_query(F.data.startswith("lang_set:"))
async def handle_lang_set_callback(callback: CallbackQuery) -> str:
    """Handle language selection. Callback data: lang_set:ru or lang_set:en."""
    if not callback.data or not callback.message or not callback.from_user:
        return "callback_invalid_data"
    parts = callback.data.split(":")
    if len(parts) != 2 or parts[1] not in ("ru", "en"):
        return "callback_invalid_lang"
    lang = parts[1]
    admin_id = callback.from_user.id
    await update_admin_language(admin_id, lang)
    confirm_text = (
        t(lang, "lang.changed_ru") if lang == "ru" else t(lang, "lang.changed_en")
    )
    await callback.answer(confirm_text, show_alert=False)
    if callback.message and isinstance(callback.message, types.Message):
        await callback.message.edit_text(confirm_text)
    return "callback_lang_set"


def _help_callback_to_key(callback_data: str) -> str:
    """Map help_getting_started -> help.getting_started etc."""
    return "help." + callback_data.replace("help_", "", 1).replace("_", ".")


@dp.callback_query(F.data.startswith("help_") & ~F.data.in_(["help_back"]))
async def handle_help_pages(callback: CallbackQuery) -> str:
    """Единый обработчик для всех страниц помощи"""
    if not callback.message or not isinstance(callback.message, types.Message):
        await callback.answer(t("en", "callback.message_inaccessible"), show_alert=True)
        return "callback_message_inaccessible"

    admin_id = callback.from_user.id if callback.from_user else 0
    admin = await get_admin(admin_id)
    lang = resolve_lang(callback.from_user, admin)

    callback_data = callback.data or ""
    text_key = _help_callback_to_key(callback_data)
    if text_key == "help.getting_started":
        text = t(lang, text_key, add_to_group_url=get_add_to_group_url())
    else:
        text = t(lang, text_key)
    if text == text_key:
        text = t(lang, "help.default_page")

    back_button = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "help.back_button"),
                    callback_data="help_back",
                )
            ]
        ]
    )

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=back_button,
        disable_web_page_preview=True,
    )
    await callback.answer()

    return f"{callback_data}_shown"


@dp.callback_query(F.data == "help_back")
async def handle_help_back(callback: CallbackQuery) -> str:
    """Возвращает к основному меню помощи"""
    if not callback.message or not isinstance(callback.message, types.Message):
        await callback.answer(t("en", "callback.message_inaccessible"), show_alert=True)
        return "callback_message_inaccessible"

    admin_id = callback.from_user.id if callback.from_user else 0
    admin = await get_admin(admin_id)
    lang = resolve_lang(callback.from_user, admin)

    text = t(lang, "help.main")
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "help.buttons.getting_started"),
                    callback_data="help_getting_started",
                ),
                InlineKeyboardButton(
                    text=t(lang, "help.buttons.training"),
                    callback_data="help_training",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "help.buttons.moderation"),
                    callback_data="help_moderation",
                ),
                InlineKeyboardButton(
                    text=t(lang, "help.buttons.commands"),
                    callback_data="help_commands",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "help.buttons.payment"),
                    callback_data="help_payment",
                ),
                InlineKeyboardButton(
                    text=t(lang, "help.buttons.support"),
                    callback_data="help_support",
                ),
            ],
        ]
    )

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )
    await callback.answer()
    return "help_back_shown"


@dp.callback_query(F.data.startswith("mark_as_not_spam:"))
async def handle_spam_ignore_callback(callback: CallbackQuery) -> str:
    """
    Обработчик колбэка для подтверждения сообщения как не спам.
    Callback data: mark_as_not_spam:{pending_id}
    """
    try:
        admin_id = callback.from_user.id

        if not callback.data or not callback.message:
            return "callback_invalid_data"

        admin = await get_admin(admin_id)
        lang = resolve_lang(callback.from_user, admin)
        try:
            await callback.answer(t(lang, "callback.safe_added"), show_alert=False)
        except Exception:
            pass

        parts = callback.data.split(":")
        if len(parts) < 2:
            return "callback_invalid_data_format"

        try:
            pending_id = int(parts[1])
        except ValueError:
            return "callback_invalid_data_format"

        row = await confirm_pending_example_as_not_spam(pending_id, admin_id)

        message = callback.message
        if not isinstance(message, types.Message):
            return "callback_invalid_message_type"

        message_text = message.text or message.caption or ""
        updated_message_text = (
            f"{message_text}\n\n✅ <b>{t(lang, 'callback.safe_added')}</b>"
        )

        if row:
            group_id = row["chat_id"]
            effective_user_id = row["effective_user_id"]

            async with asyncio.TaskGroup() as tg:
                if effective_user_id < 0:
                    tg.create_task(
                        bot.unban_chat_sender_chat(
                            group_id, sender_chat_id=effective_user_id
                        )
                    )
                else:
                    tg.create_task(
                        bot.unban_chat_member(
                            group_id, effective_user_id, only_if_banned=True
                        )
                    )
                tg.create_task(add_member(group_id, effective_user_id))
                tg.create_task(
                    bot.edit_message_text(
                        chat_id=callback.message.chat.id,
                        message_id=callback.message.message_id,
                        text=updated_message_text,
                        parse_mode="HTML",
                        reply_markup=None,
                    )
                )
        else:
            logger.warning(
                "mark_as_not_spam: pending record not found, skipping unban/add",
                extra={"pending_id": pending_id},
            )
            try:
                await bot.edit_message_text(
                    chat_id=callback.message.chat.id,
                    message_id=callback.message.message_id,
                    text=updated_message_text,
                    parse_mode="HTML",
                    reply_markup=None,
                )
            except Exception:
                pass

        return "callback_marked_as_not_spam"

    except Exception as e:
        logger.error(f"Error in spam ignore callback: {e}", exc_info=True)
        try:
            admin = (
                await get_admin(callback.from_user.id) if callback.from_user else None
            )
            lang = resolve_lang(callback.from_user, admin)
            await callback.answer(t(lang, "callback.error_generic"), show_alert=True)
        except Exception:
            pass
        return "callback_error_marking_not_spam"


@dp.callback_query(F.data.startswith("delete_spam_message:"))
async def handle_spam_confirm_callback(callback: CallbackQuery) -> str:
    """
    Handle "Delete" button in notify mode: delete original message, ban spammer,
    remove notification keyboard. Marks pending spam example as confirmed.
    """
    if not callback.data or not callback.from_user:
        return "callback_invalid_data"

    admin = await get_admin(callback.from_user.id)
    lang = resolve_lang(callback.from_user, admin)

    try:
        try:
            await callback.answer(t(lang, "callback.spam_deleted"), show_alert=False)
        except Exception:
            pass

        _, effective_user_id_str, chat_id_str, message_id_str = callback.data.split(":")
        effective_user_id = int(effective_user_id_str)
        chat_id = int(chat_id_str)
        message_id = int(message_id_str)

        if not callback.message:
            logger.warning("No notification message in callback")
            await callback.answer(t(lang, "callback.invalid_callback"), show_alert=True)
            return "callback_invalid_message"

        try:
            await bot.edit_message_reply_markup(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                reply_markup=None,
            )
        except Exception as e:
            logger.warning(f"Failed to remove keyboard from notification: {e}")

        try:

            @retry_on_network_error
            async def delete_original_message():
                return await bot.delete_message(chat_id, message_id)

            await delete_original_message()
        except TelegramBadRequest as e:
            if "message to delete not found" in e.message:
                logger.info(
                    f"Message to delete not found (likely already deleted): {chat_id}:{message_id}"
                )
            else:
                logger.warning(
                    f"Failed to delete original spam message: {e}", exc_info=True
                )
                await callback.answer(
                    t(lang, "callback.delete_failed"), show_alert=True
                )
                return "callback_error_deleting_original"
        except Exception as e:
            logger.warning(
                f"Failed to delete original spam message: {e}", exc_info=True
            )
            await callback.answer(t(lang, "callback.delete_failed"), show_alert=True)
            return "callback_error_deleting_original"

        await confirm_pending_example_as_spam(
            chat_id, message_id, callback.from_user.id
        )

        group = await get_group(chat_id)
        admin_ids = group.admin_ids if group else None
        await ban_user_for_spam(chat_id, effective_user_id, admin_ids, group_title=None)

        return "callback_spam_message_deleted"

    except Exception as e:
        logger.error(f"Error in spam confirm callback: {e}", exc_info=True)
        try:
            await callback.answer(t(lang, "callback.error_generic"), show_alert=True)
        except Exception:
            pass
        return "callback_error_deleting_spam"
