#!/usr/bin/env python3
"""
patch_headless_on.py

Reverts HEADLESS back to True after the live Move Players verification
test is done -- the real daily automated launcher needs this to run
invisibly. Run this once the test is fully finished and cleaned up.

Run once from the assignments/ directory:
    python3 patch_headless_on.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "create_shootout.py"

OLD_LINE = "HEADLESS = False  # TEMPORARY test mode -- revert to True before the real automated launcher runs again"
NEW_LINE = "HEADLESS = True  # flip to False for live selector testing against the real app"


def main():
    text = TARGET.read_text(encoding="utf-8")
    count = text.count(OLD_LINE)
    if count != 1:
        print(f"✗ Aborting: expected exactly 1 match, found {count}. "
              f"File may already be back to normal, or changed unexpectedly.")
        return 1
    text = text.replace(OLD_LINE, NEW_LINE)
    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — HEADLESS is back to True (normal automated mode).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
