#!/usr/bin/env python3
"""
Patch: signup-monitor/generate_signup_viewer.py's per-player table now opens
a new "(rejoined)" row whenever a player who genuinely withdrew later signs
back up -- whether that rejoin is a direct regular re-signup, or arrives via
a later waitlist promotion. A pure waitlist-to-regular promotion where the
player never actually withdrew still updates the same row, unchanged.

Real cases this fixes, confirmed in the live signup_viewer.html:
  - Lidia Zolnierczyk (2026-09-18 to 09-21 sheet): withdrew (regular) ->
    joined the Wait List -> later promoted to regular. Her row silently
    went from "WD" to "19" with no indication she had left and come back.
  - Bill Pollock (2026-09-07/08/09 sheet): same pattern, WL1 -> 16.

Root cause: the "joined" handler skipped row-creation entirely for the
regular half of any WL->regular transition (`if (ts, c) in transitions and
not is_wl(name): continue`), treating every promotion as a continuation of
the same still-open row -- including ones where the player's current
episode already had a genuine withdrawal recorded on it. The existing
"(rejoined)" row logic for a *direct* regular-to-regular rejoin was
otherwise working correctly and is unchanged in shape.

Fix: the decisive signal is now player_map[c]["withdrew"] -- already
tracked per-episode by the withdrawal handler, and already proven (by the
withdrawal handler's own logic) to only be set True for a genuine
departure, never for the simultaneous withdrew(WL)+joined(regular) pair
that makes up a pure promotion. If it's True, this join event (direct or
via promotion) opens a new row. If not, it's a pure promotion with no real
drop-out, and the existing row keeps updating exactly as before.

Run once from the repo root: python3 sam_signup_log_rejoin_separate_row.py
Safe to re-run: asserts the anchor matches exactly once.
"""
from pathlib import Path

path = Path("signup-monitor/generate_signup_viewer.py")
content = path.read_text()

old = (
    '            if action in ("joined*", "joined"):\n'
    '                # Skip the "regular" half of a WL→regular transition — the\n'
    '                # row already exists from their original WL join.\n'
    '                if (ts, c) in transitions and not is_wl(name):\n'
    '                    continue\n'
    '\n'
    '                if c not in player_map:\n'
)
new = (
    '            if action in ("joined*", "joined"):\n'
    '                if c not in player_map:\n'
)
n = content.count(old)
assert n == 1, f"top-guard anchor: expected exactly 1 match, found {n}"
content = content.replace(old, new)

old2 = '                elif not is_wl(name):\n'
new2 = (
    '                elif player_map[c].get("withdrew"):\n'
    '                    # A genuine withdrawal (drop-out) is already on this\n'
    '                    # player\'s current episode -- this join, whether a\n'
    '                    # direct rejoin or the "regular" half of a later\n'
    '                    # waitlist promotion, is a real sign-back-up and gets\n'
    '                    # its own row. A PURE promotion where the player never\n'
    '                    # actually withdrew does not land here at all (this\n'
    '                    # elif is false), and keeps updating the same row via\n'
    '                    # the code below, unchanged -- confirmed real cases:\n'
    '                    # Lidia Zolnierczyk (09-18 to 09-21 sheet, WD then\n'
    '                    # promoted off the waitlist) and Bill Pollock (09-07/\n'
    '                    # 08/09 sheet, same pattern). A mid-day sheet capacity\n'
    '                    # increase (e.g. 16->20) can also promote several\n'
    '                    # waitlisted players at once with no real withdrawal on\n'
    '                    # their episodes -- those still correctly fall through\n'
    '                    # to the comment below rather than this branch.\n'
)
n2 = content.count(old2)
assert n2 == 1, f"elif anchor: expected exactly 1 match, found {n2}"
content = content.replace(old2, new2)

path.write_text(content)
print("generate_signup_viewer.py updated successfully")
