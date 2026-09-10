#!/usr/bin/env python3
"""
One-off patch: fixes a real gap in run_all.sh's "status quo" shortcut.

Previously the shortcut compared master_history_raw.csv's hash from
before this run's scrape to its hash after -- if unchanged, it skipped
the summary workbook, rating engine, session viewer, storybook, and
leaderboard rebuild. This is wrong when a PRIOR run already updated the
master file (successful scrape) but then crashed before the rebuild
finished: the next run sees "no new data today" and skips the rebuild
again, even though the rebuild output was never actually regenerated
from that already-updated master file. Confirmed happened for real
2026-09-01 -- leaderboard/session viewer stuck on stale data for hours.

Fix: persist the hash of master_history_raw.csv from the last time the
rebuild block actually completed successfully, to a small state file
(data/.last_successful_rebuild_hash). Compare against THAT instead of
a same-run before/after snapshot. Only skip the rebuild when today's
hash matches the last known-successful one.

Run once from the repo root: python3 sam_fix_status_quo_shortcut.py
Safe to re-run: asserts each anchor matches exactly once.
"""
from pathlib import Path

path = Path("run_all.sh")
content = path.read_text()

# 1. Add the state file path alongside the existing path constants.
anchor1 = (
    'MASTER_FILE="data/master_history_raw.csv"\n'
    'LATEST_FILE="data/latest_scrape.csv"'
)
assert content.count(anchor1) == 1, f"anchor1 matches: {content.count(anchor1)}"
new1 = (
    'MASTER_FILE="data/master_history_raw.csv"\n'
    'LATEST_FILE="data/latest_scrape.csv"\n'
    'STATE_FILE="data/.last_successful_rebuild_hash"'
)
content = content.replace(anchor1, new1)

# 2. Replace the same-run before/after comparison with a comparison
#    against the last successfully-completed rebuild's hash.
anchor2 = (
    'if [ "$HASH_BEFORE" = "$HASH_AFTER" ]; then\n'
    '  DATA_CHANGED="NO"\n'
    'else\n'
    '  DATA_CHANGED="YES"\n'
    'fi'
)
assert content.count(anchor2) == 1, f"anchor2 matches: {content.count(anchor2)}"
new2 = (
    '# Compare against the hash recorded the last time the rebuild block\n'
    '# below actually COMPLETED successfully -- not just this run\'s own\n'
    '# before/after snapshot (see STATE_FILE comment above for why).\n'
    'LAST_SUCCESSFUL_HASH=""\n'
    'if [ -f "$STATE_FILE" ]; then\n'
    '  LAST_SUCCESSFUL_HASH=$(cat "$STATE_FILE")\n'
    'fi\n'
    '\n'
    'if [ "$HASH_AFTER" = "$LAST_SUCCESSFUL_HASH" ]; then\n'
    '  DATA_CHANGED="NO"\n'
    'else\n'
    '  DATA_CHANGED="YES"\n'
    'fi'
)
content = content.replace(anchor2, new2)

# 3. Record success at the end of the rebuild block, so next run's
#    comparison is against a hash that's guaranteed to reflect a
#    COMPLETED rebuild, not just an attempted one.
anchor3 = (
    '  echo ""\n'
    '  echo "5c. Building slim leaderboard..."\n'
    '  python3 engine/build_leaderboard_html.py\n'
    'fi'
)
assert content.count(anchor3) == 1, f"anchor3 matches: {content.count(anchor3)}"
new3 = (
    '  echo ""\n'
    '  echo "5c. Building slim leaderboard..."\n'
    '  python3 engine/build_leaderboard_html.py\n'
    '\n'
    '  # Only record success now that every rebuild step above has\n'
    '  # actually completed -- if any step above failed, the script\n'
    '  # would have already exited (set -e) before reaching this line,\n'
    '  # so STATE_FILE never gets the stale/incomplete hash.\n'
    '  echo "$HASH_AFTER" > "$STATE_FILE"\n'
    'fi'
)
content = content.replace(anchor3, new3)

path.write_text(content)
print("run_all.sh updated successfully")
