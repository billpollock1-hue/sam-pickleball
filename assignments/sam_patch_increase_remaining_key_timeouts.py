#!/usr/bin/env python3
"""
patch_increase_remaining_key_timeouts.py

One-time patch: two real failures today (Search button, Check-In All)
shared the same shape -- a short timeout waiting for a key button to
become clickable right after a page navigation or major Den backend
action. These four other timeouts share that exact shape and are
plausible candidates for the same slow-morning problem, even though
they haven't failed yet. Bumped proactively to the same generous
timeout, rather than waiting for each to fail once in production first.

Run once from the assignments/ directory:
    python3 patch_increase_remaining_key_timeouts.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "create_shootout_rating_seeded.py"

REPLACEMENTS = [
    (
        '    create_shootout_link.click(timeout=5000)',
        '    create_shootout_link.click(timeout=30000)',
    ),
    (
        '    page.get_by_role("button", name="Create Shootout", exact=True).click(timeout=5000)',
        '    page.get_by_role("button", name="Create Shootout", exact=True).click(timeout=30000)',
    ),
    (
        '    page.get_by_text("Seed Players", exact=True).click(timeout=5000)',
        '    page.get_by_text("Seed Players", exact=True).click(timeout=30000)',
    ),
    (
        '    page.get_by_text("Start Event", exact=True).click(timeout=5000)',
        '    page.get_by_text("Start Event", exact=True).click(timeout=30000)',
    ),
]


def main():
    text = TARGET.read_text(encoding="utf-8")

    for old, new in REPLACEMENTS:
        count = text.count(old)
        if count != 1:
            print(f"✗ Aborting: expected exactly 1 match for:\n  {old!r}\n"
                  f"found {count}. File may have already been patched, or changed unexpectedly.")
            return 1
        text = text.replace(old, new)

    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — 4 more key-button timeouts increased 5s -> 30s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
