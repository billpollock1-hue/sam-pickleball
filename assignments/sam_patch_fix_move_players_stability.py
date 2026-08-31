#!/usr/bin/env python3
"""
patch_fix_move_players_stability.py

One-time patch: fixes both bugs diagnosed live 2026-08-24/25 in
set_move_players().

1. The option click (get_by_text(target_text, exact=True)) matched TWO
   elements: the dropdown's closed-state display span, and the real
   clickable role="option" list item -- a strict-mode violation. Scoped
   to get_by_role("option", ...) instead, which matches only the real
   option.

2. The read-back locator ("xpath=following::vaadin-select[1]" from the
   "Move Players" label) is positionally fragile: Playwright locators
   re-resolve their query fresh on every action, so even reusing the
   same locator OBJECT can resolve to a DIFFERENT element if the page
   has changed since the first successful click -- confirmed live: after
   a failed attempt, the read-back grabbed an unrelated "Five Player
   Pools" dropdown instead, logging nonsense as the shuffle mode. Fixed
   by capturing the element's own unique "id" attribute right after
   first finding it, then building a locator from that specific ID for
   everything downstream -- guaranteeing the same DOM node is referenced
   throughout, regardless of what else changes on the page. Falls back
   to the original (less stable) locator if no id is available, so this
   can only improve reliability, never make it worse.

Run once from the assignments/ directory:
    python3 patch_fix_move_players_stability.py
"""

from pathlib import Path

TARGETS = [
    Path(__file__).resolve().parent / "create_shootout_rating_seeded.py",
    Path(__file__).resolve().parent / "create_shootout.py",
]

OLD_BLOCK = '''    target_text = "Two-up / Two-down" if shuffle_mode == "2u2b" else "One-up / One-down"
    print(f"  Setting Move Players to: {target_text}")
    move_players_field = None
    try:
        move_players_label = page.get_by_text("Move Players", exact=False)
        move_players_field = move_players_label.locator(
            "xpath=following::vaadin-select[1]"
        )
        move_players_field.click(timeout=3000)
        page.wait_for_timeout(500)
        page.get_by_text(target_text, exact=True).click(timeout=3000)
        page.wait_for_timeout(500)
    except Exception as e:'''

NEW_BLOCK = '''    target_text = "Two-up / Two-down" if shuffle_mode == "2u2b" else "One-up / One-down"
    print(f"  Setting Move Players to: {target_text}")
    move_players_field = None
    try:
        move_players_label = page.get_by_text("Move Players", exact=False)
        move_players_field = move_players_label.locator(
            "xpath=following::vaadin-select[1]"
        )
        # Capture a stable reference to THIS specific element (by id) so
        # every later action -- especially the read-back below -- targets
        # the exact same DOM node, not whatever a positional XPath happens
        # to re-resolve to after the page has changed. Confirmed live
        # 2026-08-25: after a failed click, the positional locator
        # re-resolved to an unrelated "Five Player Pools" dropdown.
        field_id = move_players_field.get_attribute("id", timeout=2000)
        if field_id:
            move_players_field = page.locator(f"#{field_id}")
        move_players_field.click(timeout=3000)
        page.wait_for_timeout(500)
        page.get_by_role("option", name=target_text, exact=True).click(timeout=3000)
        page.wait_for_timeout(500)
    except Exception as e:'''


def main():
    for target in TARGETS:
        text = target.read_text(encoding="utf-8")
        count = text.count(OLD_BLOCK)
        if count != 1:
            print(f"✗ Aborting on {target.name}: expected exactly 1 match, found {count}. "
                  f"File may have already been patched, or changed unexpectedly.")
            return 1
        text = text.replace(OLD_BLOCK, NEW_BLOCK)
        target.write_text(text, encoding="utf-8")
        print(f"✓ Patched {target} — option click scoped to role=\"option\", "
              f"read-back now uses a stable id-based locator.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
