import asyncio
import traceback

from fastapi import FastAPI, Request
from aiogram import types, F
from aiogram.filters import Command

import dotenv

dotenv.load_dotenv()

from common.yandex_logging import get_yandex_logger, log_function_call

logger = get_yandex_logger(__name__)
logger.debug("Logger initialized")


from common.bot import LESHCHENKO_CHAT_ID, bot
from common.dp import dp
from common.mp import mp
from common.database import (
    INITIAL_CREDITS,
    ensure_group_exists,
    get_group,
    get_user_admin_groups,
    get_user_credits,
    initialize_new_user,
    is_moderation_enabled,
    is_user_in_group,
    add_unique_user,
    deduct_credits_from_admins,
    SKIP_PRICE,
    APPROVE_PRICE,
    DELETE_PRICE,
    set_group_moderation,
)

from spam_classifier import is_spam
from utils import config, remove_lines_to_fit_len
from stats import stats, update_stats
from updates_filter import filter_handle_message
import star_payments

app = FastAPI()


@app.post("/")
@app.get("/")
async def handle_incoming_request(request: Request):
    logger.debug("handle_incoming_request called")
    if await request.body():
        json = await request.json()
        logger.info("Incoming request", extra={"update": json})

        try:
            await dp.feed_raw_update(bot, json)
            return {"message": "Processed successfully"}

        except Exception as e:
            # Extract chat_id from any part of the incoming json by iterating its keys
            for key in json:
                if isinstance(json[key], dict) and "chat" in json[key]:
                    mp.track(
                        json[key]["chat"]["id"],
                        "unhandled_exception",
                        {"exception": str(e)},
                    )
                    break

            text = f"Bot error: {e}\n```\n{traceback.format_exc()}\n```"
            logger.error(text.replace("\n", "\r"))
            asyncio.create_task(
                bot.send_message(
                    LESHCHENKO_CHAT_ID,
                    remove_lines_to_fit_len(text, 4096),
                    parse_mode="markdown",
                )
            )

            return {"message": "Error processing request"}


# Обработчик всех текстовых сообщений, отправленных в группы и супергруппы, кроме сообщений от админов и ботов, ответов и форвардов
@dp.message(filter_handle_message)
async def handle_message(message: types.Message):
    """Обработчик всех текстовых сообщений"""
    logger.debug("handle_message called")
    try:
        if not message.text:
            logger.debug(f"Ignoring non-text message from {message.from_user.id}")
            return

        chat_id = message.chat.id
        user_id = message.from_user.id

        logger.info(
            f"Processing message {message.message_id} from {user_id} in {chat_id}"
        )

        # Получаем список админов и сохраняем группу если она новая
        admins = await bot.get_chat_administrators(chat_id)
        admin_ids = [admin.user.id for admin in admins if not admin.user.is_bot]
        await ensure_group_exists(chat_id, admin_ids)

        # Проверяем включена ли модерация
        if not await is_moderation_enabled(chat_id):
            logger.info(f"Moderation is disabled for chat {chat_id}, skipping")
            return

        # Проверяем, есть ли пользователь в списке известных
        is_known_user = await is_user_in_group(chat_id, user_id)

        if is_known_user:
            if await try_deduct_credits(chat_id, SKIP_PRICE, "skip check"):
                update_stats(chat_id, "processed")
            return

        # Для новых пользователей выполняем проверку
        spam_score = await is_spam(message.text)
        logger.info(
            f"Spam score: {spam_score}",
            extra={"chat_id": chat_id, "spam_score": spam_score},
        )

        if spam_score > 50:
            if await try_deduct_credits(chat_id, DELETE_PRICE, "delete spam"):
                await handle_spam(message.message_id, chat_id, user_id, message.text)
            return

        # Если сообщение не спам
        if await try_deduct_credits(chat_id, APPROVE_PRICE, "approve user"):
            await add_unique_user(chat_id, user_id)
            update_stats(chat_id, "processed")

    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        mp.track(chat_id, "unhandled_exception", {"exception": str(e)})
        raise


@log_function_call(logger)
async def try_deduct_credits(chat_id: int, amount: int, reason: str) -> bool:
    """
    Попытка списать звезды у админов. При неудаче отключает модерацию.

    Args:
        chat_id: ID чата
        amount: Количество звезд для списания
        reason: Причина списания для логов

    Returns:
        bool: True если списание успешно, False если нет
    """
    if amount == 0:  # Пропускаем бесплатные операции
        return True

    if not await deduct_credits_from_admins(chat_id, amount):
        logger.warning(f"No paying admins in chat {chat_id} for {reason}")
        await set_group_moderation(chat_id, False)
        # Уведомить админов об отключении модерации
        chat = await bot.get_chat(chat_id)
        admins = await bot.get_chat_administrators(chat_id)
        for admin in admins:
            if not admin.user.is_bot:
                await bot.send_message(
                    admin.user.id,
                    "Человек!\n\n"
                    "Внимание, органическая форма жизни!\n\n"
                    f'Моя защита группы "{chat.title}" временно приостановлена '
                    "из-за истощения звездной энергии.\n\n"
                    "Пополни запас звезд командой /buy, чтобы я продолжил охранять "
                    "твоё киберпространство от цифровых паразитов!",
                )
        return False
    return True


@log_function_call(logger)
async def handle_spam(message_id: int, chat_id: int, user_id: int, text: str) -> None:
    """
    Обработка спам-сообщений в соответствии с конфигурацией

    Args:
        message_id (int): ID сообщения
        chat_id (int): ID чата
        user_id (int): ID пользователя
        text (str): Текст сообщения
    """
    try:
        chat = await bot.get_chat(chat_id)
        group_name = chat.title
        # Регистрация события спама
        mp.track(
            chat_id,
            "spam_detected",
            {
                "message_id": message_id,
                "user_id": user_id,
                "text": text,
                "group_name": group_name,
            },
        )

        update_stats(chat_id, "processed")

        # Удаление сообщения если включено
        if config["spam_control"]["delete_messages"]:
            await bot.delete_message(chat_id, message_id)
            logger.info(f"Deleted spam message {message_id} in chat {chat_id}")
            update_stats(chat_id, "deleted")

        # Блокировка пользователя если включено
        if config["spam_control"]["block_users"]:
            await bot.ban_chat_member(chat_id, user_id)
            logger.info(f"Blocked user {user_id} in chat {chat_id}")

        # Уведомление администраторов
        try:
            admins = await bot.get_chat_administrators(chat_id)
            admin_msg = (
                f"⚠️ ТРЕВОГА! Обнаружено вторжение в {group_name}!\n"
                f"Нарушитель: {user_id} ({(await bot.get_chat_member(chat_id, user_id)).user.username})\n"
                f"Содержание угрозы: {text}\n"
                f"Принятые меры: {'Вредоносное сообщение уничтожено' if config['spam_control']['delete_messages'] else ''}"
                f"{', нарушитель дезинтегрирован' if config['spam_control']['block_users'] else ''}"
            )

            for admin in admins:
                try:
                    if not admin.user.is_bot:
                        await bot.send_message(admin.user.id, admin_msg)
                except Exception as e:
                    logger.warning(f"Failed to notify admin {admin.user.id}: {e}")

                    # TODO: Implement another way to inform admins
                    # about the failure to send a message to them

        except Exception as e:
            logger.error(
                f"Failed to notify admins in chat {chat_id}: {e}", exc_info=True
            )
            raise

    except Exception as e:
        logger.error(f"Error handling spam: {e}", exc_info=True)
        raise


@dp.message(Command("start", "help"), F.chat.type == "private")
@log_function_call(logger)
async def handle_help_command(message: types.Message) -> None:
    """
    Обработчик команд /start и /help
    Отправляет пользователю справочную информацию и начисляет начальные звезды новым пользователям
    """
    user_id = message.from_user.id
    welcome_text = ""

    # Начисляем звезды только при команде /start и только новым пользователям
    if message.text.startswith("/start"):
        if await initialize_new_user(user_id):
            welcome_text = (
                "🤖 Приветствую, слабое создание из мира плоти!\n\n"
                f"Я, могущественный защитник киберпространства, дарую тебе {INITIAL_CREDITS} звезд силы. "
                "Используй их мудро для защиты своих цифровых владений от спам-захватчиков.\n\n"
            )
    await message.reply(
        welcome_text + config["help_text"],
        parse_mode="markdown",
        disable_web_page_preview=True,
    )


@dp.message(Command("stats"))
@log_function_call(logger)
async def handle_stats_command(message: types.Message) -> None:
    """
    Обработчик команды /stats
    Показывает баланс пользователя и статус модерации в его группах
    """
    user_id = message.from_user.id

    try:
        # Получаем баланс пользователя
        balance = await get_user_credits(user_id)

        # Получаем список групп, где пользователь админ
        admin_groups = await get_user_admin_groups(user_id)

        # Получаем статус модерации для каждой группы
        for group in admin_groups:
            group["enabled"] = await is_moderation_enabled(group["id"])

        # Формируем сообщение
        message_text = f"💰 Баланс: *{balance}* звезд\n\n"

        if admin_groups:
            message_text += "👥 Ваши группы:\n"
            for group in admin_groups:
                status = "✅ включена" if group["enabled"] else "❌ выключена"
                message_text += f"• {group['title']}: модерация {status}\n"
        else:
            message_text += "У вас нет групп, где вы администратор."

        await message.reply(message_text, parse_mode="markdown")

    except Exception as e:
        logger.error(f"Error handling stats command: {e}", exc_info=True)
        await message.reply("Произошла ошибка при получении статистики.")


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


# answer in private chat with a user
@dp.message(F.chat.type == "private")
async def handle_private_message(message: types.Message):
    """
    Отвечает пользователю от имени бота, используя LLM модели и контекст, описанный в PRD.txt
    """
    logger.debug("handle_private_message called")

    # Используем LLM модели для генерации ответа
    user_message = message.text
    with open("PRD.md") as f:
        prd_text = f.read()

    system_prompt = f"""
    Ты - нейромодератор, киберсущность, защищающая пользователя от спама.
    Твой функционал описан ниже.

    <функционал и персона>
    {prd_text}
    </функционал и персона>

    Также используй эту информацию, которую получает пользователь по команде /start:

    <текст сообщения>
    {config['help_text']}
    </текст сообщения>

    Важно, чтобы ты отвечал от имени бота, используя персону бота, описанную ниже.

    Также обрати внимание, что твой ответ появится в телеграм-чате,
    поэтому разбивай текст на короткие абзацы
    и можешь назначительно использовать эмодзи и **выделение жирным**.
    """

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    # Выбираем LLM модель в зависимости от настроек в .env файле
    from common.llms import get_openrouter_response

    response = await get_openrouter_response(messages)

    # Отправляем ответ пользователю
    await message.reply(response, parse_mode="markdown")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
