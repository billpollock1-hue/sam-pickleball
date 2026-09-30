#!/usr/bin/env python3
"""
Patch: scraper/merge_csv.py's validate_pools() stale-duplicate check now
also requires the two games' teams to match (as an unordered pair), not
just their posted timestamp and score.

Real false positive, 2026-09-30: Bill had to manually enter an entire
shootout's scores by hand (a player no-show required it), entering them
rapidly enough that several games shared the same minute-resolution
timestamp. Two of three games in one 4-player round-robin pool
legitimately both finished 11-4, with entirely different teams:

    Bill Pollock/Wayne Carroll beat Donna Cantrell/Lidia Zolnierczyk, 11-4
    Wayne Carroll/Lidia Zolnierczyk beat Bill Pollock/Donna Cantrell, 11-4

The existing check (added after a real 2026-09-25 incident: a stale
Vaadin-grid read borrowed one game's score for a different game) keyed
only on timestamp+score, and its own comment called two such games
"essentially impossible ... legitimately" -- true for an organic scrape,
not for rapid manual entry. It refused to write master_history_raw.csv,
silently (the merge step is called from launcher_server.py's record-date
handler, whose HTTP reply had already been lost as a "Load failed" in the
browser by the time this happened, so nothing surfaced the refusal to
Bill at all).

Fix: the dedup key now also includes the unordered pair of teams (each
team as a set of player names, so "A / B" and "B / A" are treated the
same). A genuine stale-grid read carries over the SAME team data from the
source row, not just a coincidentally matching score, so this stays just
as strict for the real incident it was built to catch while no longer
flagging two distinct games that happen to share a score.

Run once from the repo root: python3 sam_fix_validate_pools_team_check.py
Safe to re-run: asserts the anchor matches exactly once.
"""
from pathlib import Path

path = Path("scraper/merge_csv.py")
content = path.read_text()

old = (
    '        dupe_key = grp["posted"].astype(str) + "|" + grp["winning_score"].astype(str) + "-" + grp["losing_score"].astype(str)\n'
    '        dupe_counts = dupe_key.value_counts()\n'
    '        for key, n in dupe_counts[dupe_counts > 1].items():\n'
    '            ts, score = key.split("|", 1)\n'
    '            problems.append(\n'
    '                f"{label}: {n} games share both the identical posted timestamp \'{ts}\' "\n'
    '                f"AND the identical score {score} -- this is the signature of a stale/"\n'
    '                f"cross-contaminated grid read (one row\'s score borrowed from another "\n'
    '                f"game in the pool), not a real coincidence."\n'
    '            )\n'
)
new = (
    '        # Two games sharing timestamp+score alone can be a real coincidence\n'
    '        # on rapid manual entry (confirmed real, 2026-09-30) -- only flag it\n'
    '        # when the teams match too (unordered pair, so "A / B" and "B / A"\n'
    '        # count as the same team), since a genuine stale-grid read carries\n'
    '        # over the SAME team data from the source row, not just its score.\n'
    '        def _team_pair(row):\n'
    '            t1 = frozenset(p.strip() for p in str(row["winning_team"]).split("/") if p.strip())\n'
    '            t2 = frozenset(p.strip() for p in str(row["losing_team"]).split("/") if p.strip())\n'
    '            return frozenset([t1, t2])\n'
    '\n'
    '        dupe_key = list(zip(\n'
    '            grp["posted"].astype(str),\n'
    '            grp["winning_score"].astype(str) + "-" + grp["losing_score"].astype(str),\n'
    '            grp.apply(_team_pair, axis=1),\n'
    '        ))\n'
    '        seen_counts = {}\n'
    '        for key in dupe_key:\n'
    '            seen_counts[key] = seen_counts.get(key, 0) + 1\n'
    '        for key, n in seen_counts.items():\n'
    '            if n <= 1:\n'
    '                continue\n'
    '            ts, score, _ = key\n'
    '            problems.append(\n'
    '                f"{label}: {n} games share both the identical posted timestamp \'{ts}\' "\n'
    '                f"AND the identical score {score} AND the identical teams -- this is "\n'
    '                f"the signature of a stale/cross-contaminated grid read (one row\'s "\n'
    '                f"score borrowed from another game in the pool), not a real coincidence."\n'
    '            )\n'
)

n = content.count(old)
assert n == 1, f"anchor: expected exactly 1 match, found {n}"
content = content.replace(old, new)

path.write_text(content)
print("merge_csv.py updated successfully")
