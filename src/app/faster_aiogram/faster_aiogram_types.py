# fast_aiogram_types.py
import pickle
import sys
from pathlib import Path
from types import ModuleType
from typing import List, Literal, Optional, Union


class FastAiogramTypes(ModuleType):
    def __init__(self):
        super().__init__("aiogram.types")

        cache_path = Path("aiogram_types.cache")
        if cache_path.exists():
            # Load from cache
            print("Loading aiogram.types from cache")
            with open(cache_path, "rb") as f:
                cached_dict = pickle.load(f)
                self.__dict__.update(cached_dict)
        else:
            # Fallback to regular initialization
            print("Loading aiogram.types from original")
            self._init_from_original()

    def _init_from_original(self):
        import importlib.util

        # Get the original module spec before any modifications
        spec = importlib.util.find_spec("aiogram.types")
        if not spec:
            raise ImportError("Could not find aiogram.types module")

        # Create a new module from spec
        original_module = importlib.util.module_from_spec(spec)

        # Remove ourselves temporarily to allow clean import
        temp = sys.modules.pop("aiogram.types", None)

        try:
            # Execute the original module
            spec.loader.exec_module(original_module)

            # Copy all attributes except the rebuilding logic
            for attr in original_module.__dict__:
                if not attr.startswith("_rebuild"):
                    setattr(self, attr, original_module.__dict__[attr])

            # Do our fast rebuild
            essential_types = {
                "Message",
                "User",
                "Chat",
                "CallbackQuery",
                "ChatMemberUpdated",
                "LabeledPrice",
                "Invoice",
                "PreCheckoutQuery",
                "SuccessfulPayment",
                "InlineKeyboardMarkup",
                "InlineKeyboardButton",
            }

            types_namespace = {
                "List": List,
                "Optional": Optional,
                "Union": Union,
                "Literal": Literal,
                "Default": self._Default,
                **{k: v for k, v in self.__dict__.items() if k in essential_types},
            }

            for name in essential_types:
                if name in self.__dict__:
                    entity = self.__dict__[name]
                    if hasattr(entity, "model_rebuild"):
                        entity.model_rebuild(_types_namespace=types_namespace)

            # Save to cache for next time
            with open("aiogram_types.cache", "wb") as f:
                pickle.dump(self.__dict__, f)

        finally:
            # Restore ourselves to sys.modules
            sys.modules["aiogram.types"] = self
