#!/usr/bin/env python3
"""
patch_add_viewport_size.py

One-time patch: no viewport was ever specified, meaning the browser ran
at Playwright's small default (1280x720). Confirmed live 2026-08-24
(Bill directly observed the dropdown window rendering off-screen/
invisible) that this is very likely the real root cause of the
"element is not visible" Move Players click failures seen throughout
testing -- not a timing race condition as originally suspected. Sets an
explicit, generous viewport so Vaadin's dropdown overlay always has
room to render visibly regardless of page content length.

Run once from the assignments/ directory:
    python3 patch_add_viewport_size.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "create_shootout_rating_seeded.py"

OLD_BLOCK = '''        if Path(SESSION_FILE).exists():
            context = browser.new_context(storage_state=SESSION_FILE)
        else:
            context = browser.new_context()'''

NEW_BLOCK = '''        # Explicit, generous viewport -- no size was ever specified before,
        # meaning the browser ran at Playwright's small 1280x720 default.
        # Confirmed live 2026-08-24 that this very likely caused the
        # Move Players dropdown overlay to render off-screen/invisible,
        # not a timing issue as originally suspected.
        VIEWPORT = {"width": 1920, "height": 1080}
        if Path(SESSION_FILE).exists():
            context = browser.new_context(storage_state=SESSION_FILE, viewport=VIEWPORT)
        else:
            context = browser.new_context(viewport=VIEWPORT)'''


def main():
    text = TARGET.read_text(encoding="utf-8")
    count = text.count(OLD_BLOCK)
    if count != 1:
        print(f"✗ Aborting: expected exactly 1 match, found {count}. "
              f"File may have already been patched, or changed unexpectedly.")
        return 1
    text = text.replace(OLD_BLOCK, NEW_BLOCK)
    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — browser now runs with an explicit 1920x1080 "
          f"viewport, giving Vaadin's dropdown overlay room to render.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
