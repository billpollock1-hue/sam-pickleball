#!/usr/bin/env python3
"""
One-off patch: engine/build_bear_count.py -- drop stale pending rows from
data/shootout_leader_overrides.csv.

A row with a blank winner is what the admin Shootout Ties card treats as
pending. Rows are auto-added when a pool is an unresolved wins+margin tie,
but were never removed if the pool later resolved another way (e.g. Den's
official standings, or a tryout-name fix -- real case 2026-10-07 Pool 3).
After this patch, every build removes blank-winner rows whose pool is no
longer in the unresolved list. Rows with a winner are never touched.

Run once from the repo root: python3 sam_prune_stale_pending_ties.py
Safe to re-run: asserts the anchor matches exactly once.
"""
from pathlib import Path

path = Path("engine/build_bear_count.py")
content = path.read_text()

if "Prune stale pending ties" in content:
    raise SystemExit("Already applied -- nothing to do.")

anchor = "leaders_df = pd.DataFrame(leader_rows)\n"
assert content.count(anchor) == 1, f"anchor matches: {content.count(anchor)}"

new = anchor + (
    '\n'
    '# Prune stale pending ties: blank-winner rows in the overrides file whose\n'
    '# pool is no longer an unresolved tie (resolved via Den standings, etc.)\n'
    '# would otherwise keep the admin Shootout Ties card visible forever.\n'
    'if OVERRIDES_PATH.exists():\n'
    '    _ov = pd.read_csv(OVERRIDES_PATH, dtype=str).fillna("")\n'
    '    if len(_ov):\n'
    '        _still = {_pool_key(*_k) for _k, _p in unresolved_ties}\n'
    '        _keep = [\n'
    '            (str(r["winner"]).strip() != "")\n'
    '            or (_pool_key(r["play_date"], r["shootout"], r["pool"]) in _still)\n'
    '            for _, r in _ov.iterrows()\n'
    '        ]\n'
    '        if not all(_keep):\n'
    '            _dropped = int(len(_keep) - sum(_keep))\n'
    '            _ov[_keep].to_csv(OVERRIDES_PATH, index=False)\n'
    '            print(f"Removed {_dropped} stale pending tie row(s) from "\n'
    '                  f"{OVERRIDES_PATH.relative_to(REPO_ROOT)} (pool now resolved).")\n'
)
content = content.replace(anchor, new)
path.write_text(content)
print("build_bear_count.py updated successfully")
