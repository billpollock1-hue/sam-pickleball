#!/usr/bin/env python3
"""
Patch: fixes a pre-existing bug in generate_signup_viewer.py's revision-
column population, exposed by the rejoin-separate-row fix (this same
script, applied earlier) actually causing rejoin rows to be created in
practice for the first time.

Real symptom, confirmed live 2026-09-30: after the rejoin fix created a
"Bill Pollock (rejoined)" row (joined 9/8 10:55 AM), that NEW row showed a
"WD 9/7 9:50 PM" marker in an earlier column -- from BEFORE the row even
existed. The original "Bill Pollock" row, which actually owned that
withdrawal, showed nothing.

Root cause: the revision-population pass (the "Populate revision cells on
each player row" section) looks up player_map[name] for every historical
revision event, but by the time this second pass runs, player_map[name]
holds whichever row was created LAST for that name -- not whichever row
was actually open at that specific revision's own timestamp. Any name
with more than one episode (the exact case the rejoin fix now creates)
gets every one of its historical events attributed to its newest episode.

Fix: every episode (not just the current one) is now recorded, per
canonical name, with the raw timestamp it started at -- in a new
episode_history dict, built alongside player_map in the same first pass
with no change to that pass's own logic. The revision-population pass
looks up, for each event, whichever episode's start timestamp is the most
recent one at or before that event's own timestamp -- correctly routing
each historical marker to the episode that actually owned it.

Run once from the repo root: python3 sam_fix_revs_episode_misattribution.py
Safe to re-run: asserts each anchor matches exactly once.
"""
from pathlib import Path

_repo_path = Path("signup-monitor/generate_signup_viewer.py")
_deployed_path = Path("generate_signup_viewer.py")
if _repo_path.exists():
    path = _repo_path
elif _deployed_path.exists():
    path = _deployed_path
else:
    raise SystemExit(
        "Could not find generate_signup_viewer.py in either "
        f"{_repo_path} or {_deployed_path} (relative to the current "
        "directory) -- run this from the repo root or from "
        "~/Library/Application Support/PBMonitor."
    )
content = path.read_text()

if "episode_history" in content:
    print("Already applied -- nothing to do.")
    raise SystemExit(0)


def replace_once(text, old, new, label):
    n = text.count(old)
    assert n == 1, f"{label}: expected exactly 1 match, found {n}"
    return text.replace(old, new)


# 1. Introduce episode_history alongside player_map's own declaration.
old1 = "    players = []\n    player_map = {}\n"
new1 = (
    "    players = []\n"
    "    player_map = {}\n"
    "    # Every episode (not just the current one) a canonical name has had,\n"
    "    # as (start_ts, row) pairs in chronological order -- lets the\n"
    "    # revision-population pass below route each historical event to\n"
    "    # whichever episode actually owned it, instead of trusting\n"
    "    # player_map[name]'s current (possibly since-reassigned) value.\n"
    "    episode_history = {}\n"
)
content = replace_once(content, old1, new1, "episode_history declaration")

# 2. Record the episode whenever a row is created or reassigned. Both
#    creation sites set player_map[c] = p right after building p; append
#    right after each of those two assignments.
old2a = (
    '                    p = {"name": c, "joined": fmt_ts(ts), "initial": initial,\n'
    '                         "withdrew": False, "revs": []}\n'
    '                    player_map[c] = p\n'
    '                    players.append(p)\n'
)
new2a = (
    '                    p = {"name": c, "joined": fmt_ts(ts), "initial": initial,\n'
    '                         "withdrew": False, "revs": []}\n'
    '                    player_map[c] = p\n'
    '                    episode_history.setdefault(c, []).append((ts, p))\n'
    '                    players.append(p)\n'
)
content = replace_once(content, old2a, new2a, "fresh-join episode recording")

old2b = (
    '                    p = {"name": c + " (rejoined)", "joined": fmt_ts(ts),\n'
    '                         "initial": str(order), "withdrew": False, "revs": []}\n'
    '                    player_map[c] = p\n'
    '                    players.append(p)\n'
)
new2b = (
    '                    p = {"name": c + " (rejoined)", "joined": fmt_ts(ts),\n'
    '                         "initial": str(order), "withdrew": False, "revs": []}\n'
    '                    player_map[c] = p\n'
    '                    episode_history.setdefault(c, []).append((ts, p))\n'
    '                    players.append(p)\n'
)
content = replace_once(content, old2b, new2b, "rejoin episode recording")

# 3. Helper to pick the right episode for a given name + timestamp.
old3 = "    # ── Populate revision cells on each player row"
new3 = (
    '    def _episode_at(c, at_ts):\n'
    '        """The row that was actually open for canonical name c at at_ts --\n'
    '        the most recently started episode whose start_ts <= at_ts. Falls\n'
    '        back to player_map[c] (the current episode) if c has no recorded\n'
    '        episode history, which should not normally happen but keeps this\n'
    '        at least as safe as the old lookup in that edge case."""\n'
    '        eps = episode_history.get(c)\n'
    '        if not eps:\n'
    '            return player_map.get(c)\n'
    '        result = None\n'
    '        for start_ts, row in eps:\n'
    '            if start_ts <= at_ts:\n'
    '                result = row\n'
    '            else:\n'
    '                break\n'
    '        return result\n'
    '\n'
    '    # ── Populate revision cells on each player row'
)
content = replace_once(content, old3, new3, "_episode_at helper")

# 4. Redirect the three lookup sites in the revision-population pass to
#    use _episode_at(name, rev["ts"]) instead of player_map[name] directly.
old4 = (
    '        for wd_c in rev["withdrawals"]:\n'
    '            if wd_c in player_map:\n'
    '                if rev["withdrawal_action"].get(wd_c) == "removed_auto":\n'
    '                    player_map[wd_c]["revs"][ri] = {"t": "auto", "v": f"AUTO {fmt_ts(rev[\'ts\'])}", "title": fmt_full_ts(rev[\'ts\']) + " — removed by shootout launcher (court-count trim)"}\n'
    '                else:\n'
    '                    player_map[wd_c]["revs"][ri] = {"t": "wd", "v": f"WD {fmt_ts(rev[\'ts\'])}", "title": fmt_full_ts(rev[\'ts\'])}\n'
)
new4 = (
    '        for wd_c in rev["withdrawals"]:\n'
    '            wd_row = _episode_at(wd_c, rev["ts"])\n'
    '            if wd_row is not None:\n'
    '                if rev["withdrawal_action"].get(wd_c) == "removed_auto":\n'
    '                    wd_row["revs"][ri] = {"t": "auto", "v": f"AUTO {fmt_ts(rev[\'ts\'])}", "title": fmt_full_ts(rev[\'ts\']) + " — removed by shootout launcher (court-count trim)"}\n'
    '                else:\n'
    '                    wd_row["revs"][ri] = {"t": "wd", "v": f"WD {fmt_ts(rev[\'ts\'])}", "title": fmt_full_ts(rev[\'ts\'])}\n'
)
content = replace_once(content, old4, new4, "withdrawal lookup redirect")

old5 = (
    '        for c, val in rev["reorders"].items():\n'
    '            if c not in player_map:\n'
    '                continue\n'
    '            if isinstance(val, tuple) and val[0] == "wl":\n'
    '                player_map[c]["revs"][ri] = {"t": "rev", "v": f"WL{val[1]}"}\n'
    '            else:\n'
    '                player_map[c]["revs"][ri] = {"t": "rev", "v": str(val)}\n'
)
new5 = (
    '        for c, val in rev["reorders"].items():\n'
    '            reorder_row = _episode_at(c, rev["ts"])\n'
    '            if reorder_row is None:\n'
    '                continue\n'
    '            if isinstance(val, tuple) and val[0] == "wl":\n'
    '                reorder_row["revs"][ri] = {"t": "rev", "v": f"WL{val[1]}"}\n'
    '            else:\n'
    '                reorder_row["revs"][ri] = {"t": "rev", "v": str(val)}\n'
)
content = replace_once(content, old5, new5, "reorder lookup redirect")

old6 = (
    '        for c, new_order in rev["transitions"].items():\n'
    '            if c in player_map:\n'
    '                player_map[c]["revs"][ri] = {"t": "promoted", "v": str(new_order)}\n'
)
new6 = (
    '        for c, new_order in rev["transitions"].items():\n'
    '            promo_row = _episode_at(c, rev["ts"])\n'
    '            if promo_row is not None:\n'
    '                promo_row["revs"][ri] = {"t": "promoted", "v": str(new_order)}\n'
)
content = replace_once(content, old6, new6, "promotion lookup redirect")

path.write_text(content)
print("generate_signup_viewer.py updated successfully")
