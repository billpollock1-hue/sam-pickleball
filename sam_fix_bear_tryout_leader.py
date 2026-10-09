#!/usr/bin/env python3
"""
One-off patch: engine/build_bear_count.py -- resolve a Den-official pool
leader recorded as 'Den New Player Tryout' to the real player name via
data/tryout_name_fixes.csv (date,real_name).

Bug (2026-10-07, shootout 1 Pool 3): Den's rank-1 finisher was stored as
the raw tryout text, which matches no player in the pool, so the code fell
back to its own wins+margin derivation, saw Paul Batie / Jay Mann tied,
and raised an unresolved Shootout Tie.

Run once from the repo root: python3 sam_fix_bear_tryout_leader.py
Safe to re-run: asserts the anchor matches exactly once.
"""
from pathlib import Path

path = Path("engine/build_bear_count.py")
content = path.read_text()

anchor = (
    '    for _, r in standings_df[standings_df["rank"] == "1"].iterrows():\n'
    '        official_leader_map[_pool_key(r["play_date"], r["shootout"], r["pool"])] = r["player"].strip()\n'
)
assert content.count(anchor) == 1, f"anchor matches: {content.count(anchor)}"

new = (
    '    # Den shows tryout players as raw "Den New Player Tryout (...)" text;\n'
    '    # substitute the real name from data/tryout_name_fixes.csv (date,real_name)\n'
    '    # so the leader matches the name used in the game log.\n'
    '    _tryout_fixes = {}\n'
    '    _fix_path = REPO_ROOT / "data" / "tryout_name_fixes.csv"\n'
    '    if _fix_path.exists():\n'
    '        _fix_df = pd.read_csv(_fix_path, dtype=str).fillna("")\n'
    '        for _, _fr in _fix_df.iterrows():\n'
    '            if _fr["date"].strip() and _fr["real_name"].strip():\n'
    '                _tryout_fixes[_fr["date"].strip()] = _fr["real_name"].strip()\n'
    '    for _, r in standings_df[standings_df["rank"] == "1"].iterrows():\n'
    '        _leader = r["player"].strip()\n'
    '        if _leader.lower().startswith("den new player tryout"):\n'
    '            _leader = _tryout_fixes.get(r["play_date"].strip(), _leader)\n'
    '        official_leader_map[_pool_key(r["play_date"], r["shootout"], r["pool"])] = _leader\n'
)
content = content.replace(anchor, new)
path.write_text(content)
print("build_bear_count.py updated successfully")
