#!/usr/bin/env python3
"""
Audit i18n: compare keys used via t() in src/app with string leaves in locales/*.yaml
(logic lives in tests/support/i18n_keys_audit.py).

Usage:
  python3 scripts/audit_i18n.py            # report missing keys, exit 1 if any
  python3 scripts/audit_i18n.py --unused   # also list possibly-unused YAML keys
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_src = str(_PROJECT_ROOT / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tests.support.i18n_keys_audit import run_i18n_keys_audit, unused_yaml_keys


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit i18n keys vs YAML locales.")
    parser.add_argument(
        "--unused",
        action="store_true",
        help="List YAML string keys not in the referenced-key set (heuristic)",
    )
    args = parser.parse_args()

    result = run_i18n_keys_audit()
    print("Referenced keys:", len(result.referenced_keys))

    if result.dynamic_t_calls:
        print("\nNon-literal second argument to t() (review for missing keys):")
        for path, line, expr in sorted(result.dynamic_t_calls):
            print(f"  src/app/{path}:{line}: {expr}")

    exit_code = 0
    for lang in ("en", "ru"):
        miss = result.missing_by_lang[lang]
        if miss:
            exit_code = 1
            print(f"\nMissing in {lang}.yaml ({len(miss)}):")
            for k in miss:
                print(f"  {k}")

    if args.unused:
        for lang, keys in unused_yaml_keys(result).items():
            print(f"\nPossibly unused in {lang}.yaml ({len(keys)}):")
            for k in keys:
                print(f"  {k}")

    if exit_code == 0:
        print("\nAll referenced keys exist as strings in en.yaml and ru.yaml.")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
