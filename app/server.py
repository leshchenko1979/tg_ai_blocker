import asyncio
import traceback

from fastapi import FastAPI, Request

from common.bot import LESHCHENKO_CHAT_ID, bot
from common.dp import dp
from common.mp import mp
from common.yandex_logging import get_yandex_logger
from utils import remove_lines_to_fit_len

logger = get_yandex_logger(__name__)

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
