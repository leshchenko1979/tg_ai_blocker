import asyncio
import logging
import traceback

import logfire
from aiohttp import web

from .common.bot import LESHCHENKO_CHAT_ID, bot
from .common.mp import mp
from .common.utils import remove_lines_to_fit_len
from .handlers.dp import dp

logger = logging.getLogger(__name__)

routes = web.RouteTableDef()
app = web.Application()


@routes.post("/")
@routes.get("/")
@logfire.instrument()
async def handle_incoming_request(request: web.Request):
    if not await request.read():
        return web.Response()

    json = await request.json()
    logger.info("Incoming request", extra={"update": json})

    try:
        await dp.feed_raw_update(bot, json)
        return web.json_response({"message": "Processed successfully"})

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

        text = f"Bot error: `{e}`\n```\n{traceback.format_exc()}\n```"
        logger.error(text.replace("\n", "\r"))
        asyncio.create_task(
            bot.send_message(
                LESHCHENKO_CHAT_ID,
                remove_lines_to_fit_len(text, 4096),
                parse_mode="markdown",
            )
        )

        return web.json_response({"message": "Error processing request"})


app.add_routes(routes)
