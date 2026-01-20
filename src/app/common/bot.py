import os
import sys

from aiogram import Bot

bot = Bot(token=os.getenv("BOT_TOKEN"))

# Admin chat ID is now loaded from config.yaml

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

try:
    import yaml

    with open("config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    system = config.get("system", {})
    LESHCHENKO_CHAT_ID = system.get("admin_chat_id", 133526395)

except Exception:
    # Fallback value if config loading fails
    LESHCHENKO_CHAT_ID = 133526395
