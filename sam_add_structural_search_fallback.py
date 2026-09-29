#!/usr/bin/env python3
"""
Patch: assignments/create_shootout_rating_seeded.py's Search button wait now
races two independent locators via Playwright's Locator.or_(), instead of
relying on the accessible-name selector alone.

Why: two separate Playwright traces (2026-09-11, 2026-09-21) showed the
exact same symptom -- the Search button fully visible and unchanged for the
entire 150s wait, yet get_by_role("button", name="Search", exact=True)
never resolved. That selector is otherwise confirmed correct (Playwright's
own strict-mode error message identified it as the unique locator when a
looser substring match briefly matched two buttons). The suspected cause,
never proven: the browser's accessible-name computation for this button is
occasionally unreliable even though the button looks identical on screen.

Confirmed fresh from the live page via DevTools, 2026-09-28:
    <vaadin-button class="pd-primary-button" ...>
      <vaadin-icon icon="vaadin:search" slot="prefix"></vaadin-icon>
      "Search"
    </vaadin-button>
That structure gives an independent way to find the same button, via CSS
class + icon rather than the accessible name Chromium computes.

Locator.or_() waits for EITHER condition and clicks whichever one actually
resolves -- both should identify the same single physical button (there is
only one search-icon button on this page), so this doesn't reintroduce the
strict-mode multi-match problem the exact-match fix addressed. It also
avoids doubling the worst-case wait: a sequential try-then-fallback would
pay the full 150s timeout before ever trying the second selector.

Run once from the repo root: python3 sam_add_structural_search_fallback.py
Safe to re-run: asserts the anchor matches exactly once.
"""
from pathlib import Path

path = Path("assignments/create_shootout_rating_seeded.py")
content = path.read_text()

old = (
    '        search_button = page.get_by_role("button", name="Search", exact=True)\n'
    '        search_button.wait_for(state="visible", timeout=150000)\n'
    '        search_button.click()\n'
)
new = (
    '        # Races two independent ways of finding the same button (accessible\n'
    '        # name vs. CSS class + icon) via or_(), rather than relying on either\n'
    '        # alone -- confirmed real incident: this button has twice been seen\n'
    '        # fully visible and unchanged for the entire wait while the\n'
    '        # accessible-name selector alone still timed out (2026-09-11,\n'
    '        # 2026-09-21 traces). Both locators should resolve to the same single\n'
    '        # physical button (only one search-icon button on this page), so this\n'
    '        # does not reintroduce the earlier strict-mode multi-match problem.\n'
    '        by_name = page.get_by_role("button", name="Search", exact=True)\n'
    '        by_structure = page.locator(\'vaadin-button.pd-primary-button:has(vaadin-icon[icon="vaadin:search"])\')\n'
    '        search_button = by_name.or_(by_structure)\n'
    '        search_button.wait_for(state="visible", timeout=150000)\n'
    '        search_button.click()\n'
)

n = content.count(old)
assert n == 1, f"anchor: expected exactly 1 match, found {n}"
content = content.replace(old, new)

path.write_text(content)
print("create_shootout_rating_seeded.py updated successfully")
