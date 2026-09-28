#!/usr/bin/env python3
"""
Patch: fixes the "DEN ASSIGNMENTS STALE" message in generate_assignments_viewer.py.

Real issue, flagged 2026-09-28: after cancelling a no-shootout day, the
NEXT playdate's preview still showed a red "DEN ASSIGNMENTS STALE" warning.
Investigated and found two real problems with the message itself, not with
the underlying data:

  1. It's wrongly framed as staleness at all. den_current is set once per
     refresh_assignments.py run (a single fetch from Den's ratings page)
     and stamped identically onto EVERY date refreshed in that pass --
     it has no per-date meaning, and nothing about a date having no
     shootout makes its own ratings (through the last real play date)
     stale. There's nothing wrong with the date; Den's separate Step/%
     ratings simply weren't fetched this cycle.

  2. "Will refresh automatically at the next scheduled update" is false.
     An expired Den login session does not self-correct on the next run
     -- confirmed by reading refresh_date()'s Den-ratings fetch: it stays
     expired until someone logs in again, which is exactly what
     run_all.sh's own console output already tells Bill to do.

Fix: reworded to state what's actually true (Den's Step/% ratings
weren't available this cycle; SAM's own ratings below are unaffected)
and to point at the real remedy instead of a false promise. Moved off
the shared .pg-warn class (kept as-is for the two genuinely urgent,
accurate warnings it's still used for: too few signups, and SAM's own
ratings pending a scrape) onto a new, calmer .pg-info style, since this
is routine information, not something requiring concern.

Run once from the repo root: python3 sam_fix_den_stale_message.py
Safe to re-run: asserts each anchor matches exactly once.
"""
from pathlib import Path

path = Path("assignments/generate_assignments_viewer.py")
content = path.read_text()


def replace_once(text, old, new, label):
    n = text.count(old)
    assert n == 1, f"{label}: expected exactly 1 match, found {n}"
    return text.replace(old, new)


# 1. New CSS class, right after .pg-warn
old_css = '.pg-warn { font-size: 12px; font-weight: bold; color: #c00000; margin-top: 3px; }\n'
new_css = old_css + '.pg-info { font-size: 12px; color: #666; margin-top: 3px; }\n'
content = replace_once(content, old_css, new_css, "CSS block")

# 2. The message itself
old_msg = (
    '      h += `<div class="pg-warn">⚠ DEN ASSIGNMENTS STALE — '
    'Step/% data will refresh automatically at the next scheduled update.</div>`;'
)
new_msg = (
    "      h += `<div class=\"pg-info\">Den's Step/% ratings weren't available "
    "this cycle (login session needs a manual refresh) — SAM's own ratings "
    "below are unaffected.</div>`;"
)
content = replace_once(content, old_msg, new_msg, "message")

path.write_text(content)
print("generate_assignments_viewer.py updated successfully")
