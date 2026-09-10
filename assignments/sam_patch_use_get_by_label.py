#!/usr/bin/env python3
"""
patch_use_get_by_label.py

One-time patch: even a custom marker attribute set directly on the
element didn't survive -- confirmed live 2026-08-25, same wrong value
reproduced identically. Most likely explanation: Vaadin destroys and
recreates the underlying element on close/error, so nothing set on the
original element beforehand can survive, no matter how it's tagged.

Replaces the whole positional-locator/marker-attribute approach with
Playwright's purpose-built tool for this: get_by_label("Move Players"),
which finds the form control associated with that label through its
accessibility relationship, re-resolved fresh and correctly every
single time it's used -- regardless of any element recreation, since
it never depends on remembering a specific prior element at all.

Run once from the assignments/ directory:
    python3 patch_use_get_by_label.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "create_shootout_rating_seeded.py"

OLD_BLOCK = '''    target_text = "Two-up / Two-down" if shuffle_mode == "2u2b" else "One-up / One-down"
    print(f"  Setting Move Players to: {target_text}")
    move_players_field = None
    try:
        move_players_label = page.get_by_text("Move Players", exact=False)
        move_players_field = move_players_label.locator(
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
        move_players_field.click(timeout=3000)
        page.wait_for_timeout(500)
        page.get_by_role("option", name=target_text, exact=True).click(timeout=3000)
        page.wait_for_timeout(500)
    except Exception as e:
        print(f"  \\u26a0 Could not set Move Players field: {e} -- leaving Den's "
              f"existing value untouched rather than failing the whole launch.")
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        except Exception:
            pass
        _debug_screenshot(page, "move_players_field")

    try:
        if move_players_field is None:
            move_players_label = page.get_by_text("Move Players", exact=False)
            move_players_field = move_players_label.locator(
                "xpath=following::vaadin-select[1]"
            )
        actual_value = move_players_field.inner_text(timeout=2000).strip()
        return actual_value if actual_value else "Unknown"
    except Exception:
        return "Unknown"'''

NEW_BLOCK = '''    target_text = "Two-up / Two-down" if shuffle_mode == "2u2b" else "One-up / One-down"
    print(f"  Setting Move Players to: {target_text}")
    # get_by_label re-resolves fresh, via the field's own accessibility
    # label association, every single time it's used -- never depends on
    # remembering a specific prior element. Two earlier approaches (a
    # positional XPath, then a custom marker attribute set directly on
    # the element) both failed live 2026-08-25, most likely because
    # Vaadin destroys and recreates the underlying element on close/
    # error, so nothing set beforehand on the original element can
    # survive regardless of how it was tagged.
    move_players_field = page.get_by_label("Move Players")
    try:
        move_players_field.click(timeout=3000)
        page.wait_for_timeout(500)
        page.get_by_role("option", name=target_text, exact=True).click(timeout=3000)
        page.wait_for_timeout(500)
    except Exception as e:
        print(f"  \\u26a0 Could not set Move Players field: {e} -- leaving Den's "
              f"existing value untouched rather than failing the whole launch.")
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        except Exception:
            pass
        _debug_screenshot(page, "move_players_field")

    try:
        actual_value = move_players_field.inner_text(timeout=2000).strip()
        return actual_value if actual_value else "Unknown"
    except Exception:
        return "Unknown"'''


def main():
    text = TARGET.read_text(encoding="utf-8")
    count = text.count(OLD_BLOCK)
    if count != 1:
        print(f"✗ Aborting: expected exactly 1 match, found {count}. "
              f"File may have already been patched, or changed unexpectedly.")
        return 1
    text = text.replace(OLD_BLOCK, NEW_BLOCK)
    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — now uses get_by_label(\"Move Players\"), "
          f"re-resolved fresh on every action instead of a remembered element.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
