#!/usr/bin/env python3
"""
patch_headless_off.py

TEMPORARY, test-only: flips HEADLESS to False so create_shootout.py
opens a real, visible browser window instead of running invisibly.
Meant for today's live Move Players verification test.

IMPORTANT: revert this afterward with patch_headless_on.py (or by hand)
before the automated launcher runs again -- the real daily automation
needs HEADLESS = True to run invisibly.

Run once from the assignments/ directory:
    python3 patch_headless_off.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "create_shootout.py"

OLD_LINE = "HEADLESS = True  # flip to False for live selector testing against the real app"
NEW_LINE = "HEADLESS = False  # TEMPORARY test mode -- revert to True before the real automated launcher runs again"


def main():
    text = TARGET.read_text(encoding="utf-8")
    count = text.count(OLD_LINE)
    if count != 1:
        print(f"✗ Aborting: expected exactly 1 match, found {count}. "
              f"File may already be in test mode, or changed unexpectedly.")
        return 1
    text = text.replace(OLD_LINE, NEW_LINE)
    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — HEADLESS is now False (TEMPORARY, test mode). "
          f"Remember to revert before the real automated launcher runs again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
