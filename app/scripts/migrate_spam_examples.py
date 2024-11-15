import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)

# Add the app directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.database.spam_examples import initialize_spam_examples
from utils import config


async def migrate_spam_examples():
    """Migrate spam examples from config.yaml to Redis"""
    examples = config.get("spam_examples", [])
    success = await initialize_spam_examples(examples)
    if success:
        print("Successfully migrated spam examples to Redis")
    else:
        print("Failed to migrate spam examples to Redis")


if __name__ == "__main__":
    asyncio.run(migrate_spam_examples())
