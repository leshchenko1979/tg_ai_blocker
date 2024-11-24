import sys

# Remove any existing import first
if "aiogram.types" in sys.modules:
    del sys.modules["aiogram.types"]

# Now import our fast version
from .faster_aiogram_types import FastAiogramTypes

# Install our fast version
sys.modules["aiogram.types"] = FastAiogramTypes()
