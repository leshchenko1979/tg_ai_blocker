import os
import pickle
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
APP_DIR = ROOT_DIR / "app"

assert APP_DIR.exists()

sys.path.append(str(APP_DIR))


def original_import():
    start = time.time()
    import aiogram.types  # noqa

    end = time.time()
    print(f"Original import took: {end - start:.2f} seconds")
    return end - start


def cached_import():
    # Clear modules
    import sys

    if "aiogram.types" in sys.modules:
        del sys.modules["aiogram.types"]

    start = time.time()
    from faster_aiogram import bootstrap  # noqa

    end = time.time()
    print(f"Fast import took: {end - start:.2f} seconds")
    return end - start


def test_cache_file():
    cache_path = Path("aiogram_types.cache")
    assert cache_path.exists(), "Cache file not found!"
    size = os.path.getsize(cache_path)
    with open(cache_path, "rb") as f:
        data = pickle.load(f)
    print(f"Cache file size: {size/1024:.1f}KB")
    print(f"Cached types: {len([k for k in data.keys() if not k.startswith('_')])}")


if __name__ == "__main__":
    print("Testing aiogram types loading...")
    original_time = original_import()
    cache_exists = test_cache_file()
    cached_time = cached_import()

    if cached_time < original_time:
        print(
            f"Speed improvement: {(original_time-cached_time)/original_time*100:.1f}%"
        )
