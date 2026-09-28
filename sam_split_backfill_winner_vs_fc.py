#!/usr/bin/env python3
"""
Patch: engine/apply_backfill.py runs merge_standings() (the shootout-winner
/ pool-standings piece) by default. fill_first_choice() becomes opt-in via
--first-choice, since that thread is deliberately deferred for now.

Run once from the repo root: python3 sam_split_backfill_winner_vs_fc.py
Safe to re-run: asserts the anchor matches exactly once.
"""
from pathlib import Path

path = Path("engine/apply_backfill.py")
content = path.read_text()

old = (
    'if __name__ == "__main__":\n'
    '    merge_standings()\n'
    '    fill_first_choice()\n'
)
new = (
    'if __name__ == "__main__":\n'
    '    # first_choice backfilling is deliberately deferred for now -- only\n'
    '    # the standings/winner merge runs by default. Pass --first-choice to\n'
    '    # also run fill_first_choice() when that thread is picked back up.\n'
    '    merge_standings()\n'
    '    if "--first-choice" in sys.argv:\n'
    '        fill_first_choice()\n'
    '    else:\n'
    '        print("Skipping first_choice backfill (deferred) -- pass --first-choice to include it.")\n'
)

n = content.count(old)
assert n == 1, f"anchor: expected exactly 1 match, found {n}"
content = content.replace(old, new)

path.write_text(content)
print("apply_backfill.py updated successfully")
