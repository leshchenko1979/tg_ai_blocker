#!/usr/bin/env python3
import asyncio
import os
import sys
from dotenv import load_dotenv
from aiogram import Bot

# Add project root to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

from src.app.database.admin_operations import get_all_admins
from src.app.database.postgres_connection import get_pool, close_pool

async def main():
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise ValueError("BOT_TOKEN environment variable is not set")

    bot = Bot(token=bot_token)
    await get_pool()  # Initialize the connection pool
    try:
        admins = await get_all_admins()
        print('\nAdministrators List:')
        print('-------------------')
        for admin in admins:
            try:
                user_info = await bot.get_chat(admin.admin_id)
                full_name = f"{user_info.first_name or ''} {user_info.last_name or ''}".strip()
                print(f'ID: {admin.admin_id}')
                print(f'Username: {admin.username or "Not set"}')
                print(f'Full Name: {full_name or "Not available"}')
                print(f'Credits: {admin.credits}')
                print(f'Delete Spam: {admin.delete_spam}')
                print(f'Created: {admin.created_at}')
                print(f'Last Active: {admin.last_updated}')
            except Exception:
                print(f'ID: {admin.admin_id}')
                print(f'Username: {admin.username or "Not set"}')
                print('Full Name: Unable to fetch (User may have blocked the bot)')
                print(f'Credits: {admin.credits}')
                print(f'Delete Spam: {admin.delete_spam}')
                print(f'Created: {admin.created_at}')
                print(f'Last Active: {admin.last_updated}')
            print('-------------------')
    finally:
        await bot.session.close()
        await close_pool()  # Clean up the connection pool

if __name__ == '__main__':
    asyncio.run(main())
