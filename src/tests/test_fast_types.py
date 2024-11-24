import os
import pickle
import time
from pathlib import Path


def test_original_import():
    start = time.time()
    end = time.time()
    print(f"Original import took: {end - start:.2f} seconds")
    return end - start


def test_cached_import():
    # Clear modules
    import sys

    if "aiogram.types" in sys.modules:
        del sys.modules["aiogram.types"]

    start = time.time()
    from ..app.faster_aiogram import bootstrap  # noqa

    end = time.time()
    print(f"Fast import took: {end - start:.2f} seconds")
    return end - start


def test_cache_file():
    cache_path = Path("aiogram_types.cache")
    if cache_path.exists():
        size = os.path.getsize(cache_path)
        with open(cache_path, "rb") as f:
            data = pickle.load(f)
        print(f"Cache file size: {size/1024:.1f}KB")
        print(f"Cached types: {len([k for k in data.keys() if not k.startswith('_')])}")
        return True
    print("Cache file not found!")
    return False


if __name__ == "__main__":
    print("Testing aiogram types loading...")
    original_time = test_original_import()
    cache_exists = test_cache_file()
    cached_time = test_cached_import()

    if cached_time < original_time:
        print(
            f"Speed improvement: {(original_time-cached_time)/original_time*100:.1f}%"
        )
