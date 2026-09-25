#!/usr/bin/env python3
"""
patch_increase_checkin_timeout.py

One-time patch: real automated log showed 4 of 5 errors on 2026-08-25
were this exact step timing out at 5000ms waiting for "Check-In All" to
become clickable -- same root cause already diagnosed and fixed for the
Search button (45s -> 90s): Den's page can genuinely be slow some
mornings, and a short timeout doesn't give it enough buffer. Applying
the same fix here.

Run once from the assignments/ directory:
    python3 patch_increase_checkin_timeout.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "create_shootout_rating_seeded.py"

OLD_LINE = '    page.get_by_text("Check-In All", exact=True).click(timeout=5000)'
NEW_LINE = '    page.get_by_text("Check-In All", exact=True).click(timeout=30000)'


def main():
    text = TARGET.read_text(encoding="utf-8")
    count = text.count(OLD_LINE)
    if count != 1:
        print(f"✗ Aborting: expected exactly 1 match, found {count}. "
              f"File may have already been patched, or changed unexpectedly.")
        return 1
    text = text.replace(OLD_LINE, NEW_LINE)
    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — Check-In All click timeout increased 5s -> 30s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
