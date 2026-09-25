#!/usr/bin/env python3
"""
One-off patch: adds a comment documenting a real edge case discovered
2026-09-23 -- a mid-day capacity increase (16->20) caused three
waitlisted players (Jackie Maniaci, Bruce Blair, Lidia Zolnierczyk) to
all get simultaneously reclassified from "Wait List" to regular by
DEN itself. The monitor's diffing has no concept of a capacity change
-- it only compares two text snapshots -- so it logged this as six
separate withdrew/joined pairs, one per player, all at the identical
timestamp (2026-09-21 09:54:52), which the display code's per-player
rejoin logic doesn't specifically recognize as a single bulk event.

Not fixed (deliberately) -- confirmed rare (a capacity change is an
occasional admin action, not a routine occurrence), the raw log data
is never actually lost or wrong (just requires reading the pattern:
multiple WL->regular pairs at one identical timestamp), and nothing
downstream (court assignments, ratings) is affected by it -- purely
a display-clarity question, not a functional bug. This comment exists
so a future read of this code isn't confused by the same case again.

Run once from the repo root: python3 sam_add_capacity_change_comment.py
Safe to re-run: asserts the anchor matches exactly once.
"""
from pathlib import Path

path = Path("signup-monitor/generate_signup_viewer.py")
content = path.read_text()

anchor = (
    '                elif not is_wl(name):\n'
    '                    # Withdrew and rejoined — add a second row.'
)
assert content.count(anchor) == 1, f"anchor matches: {content.count(anchor)}"

new = (
    '                elif not is_wl(name):\n'
    '                    # NOTE (2026-09-23): a mid-day sheet capacity increase\n'
    '                    # (e.g. 16->20) can cause several waitlisted players to\n'
    '                    # be simultaneously reclassified from Wait List to\n'
    '                    # regular by DEN itself -- confirmed real, e.g. three\n'
    '                    # players all at timestamp 2026-09-21 09:54:52. This\n'
    '                    # diffing logic has no concept of "the sheet\'s capacity\n'
    '                    # changed" -- it only compares text snapshots -- so it\n'
    '                    # logs that as N separate withdrew(WL)+joined(regular)\n'
    '                    # pairs, all at one identical timestamp, which this\n'
    '                    # per-player rejoin branch below doesn\'t specifically\n'
    '                    # recognize as one bulk event. Deliberately not handled\n'
    '                    # specially: rare, the raw log data is never lost (just\n'
    '                    # needs reading the pattern), and nothing downstream\n'
    '                    # (court assignments, ratings) is affected -- a display-\n'
    '                    # clarity question only, not a functional bug.\n'
    '                    # Withdrew and rejoined — add a second row.'
)
content = content.replace(anchor, new)

path.write_text(content)
print("generate_signup_viewer.py updated successfully")
