#!/usr/bin/env python3
"""
patch_use_custom_marker_attribute.py

One-time patch: yesterday's fix assumed Den's page already had a stable
"id" attribute on the Move Players vaadin-select element -- confirmed
live 2026-08-25 that this assumption was wrong (the read-back bug
reproduced identically). Rather than depend on Den's page providing a
stable identifier, this sets our OWN custom marker attribute directly
on the element the moment we first find it, then re-locates by that
exact marker for every later action. This has no dependency on
anything Den's page happens to provide.

Run once from the assignments/ directory:
    python3 patch_use_custom_marker_attribute.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "create_shootout_rating_seeded.py"

OLD_BLOCK = '''        move_players_field = move_players_label.locator(
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
        move_players_field.click(timeout=3000)'''

NEW_BLOCK = '''        move_players_field = move_players_label.locator(
            "xpath=following::vaadin-select[1]"
        )
        # Tag this specific element with our own marker attribute so
        # every later action -- especially the read-back below -- targets
        # the exact same DOM node, regardless of what else changes on
        # the page. The earlier id-based approach assumed Den's page
        # already had a stable "id" on this element -- confirmed live
        # 2026-08-25 that assumption was wrong (same bug reproduced).
        # Setting our own attribute has no dependency on anything Den's
        # page happens to provide.
        move_players_field.evaluate(
            "el => el.setAttribute('data-sam-marker', 'move-players')"
        )
        move_players_field = page.locator('[data-sam-marker="move-players"]')
        move_players_field.click(timeout=3000)'''


def main():
    text = TARGET.read_text(encoding="utf-8")
    count = text.count(OLD_BLOCK)
    if count != 1:
        print(f"✗ Aborting: expected exactly 1 match, found {count}. "
              f"File may have already been patched, or changed unexpectedly.")
        return 1
    text = text.replace(OLD_BLOCK, NEW_BLOCK)
    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — Move Players field now marked with our "
          f"own custom attribute for stable re-location.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
