"""
One-off cleanup: removes exact duplicate game rows from
data/master_history_raw.csv.

Discovered case: every one of 2026-09-25's 18 real games is logged TWICE
in the history file (36 rows for 18 games), each pair posted about two
hours apart with identical teams and an identical score. Den's own site
agrees there were only 2 real shootout events that morning (18 games
total), so the extra 18 rows are phantom re-logs, not real games -- most
likely Den re-posting/resyncing that day's results into the export at some
point. A second, smaller case: 2023-09-27 has one exact duplicate pair
(same two teams, same score, ~4 hours apart). Both were found by scanning
the entire file for rows sharing the same day, pool, unordered team
pairing, and score -- the same signature a real round-robin game can only
produce once.

A duplicate pair is NOT the same thing as the swapped-order ties that
apply_backfill.py's/apply_backfill_redated.py's roster-fallback pass
handles -- those are two DIFFERENT games whose relative order was
ambiguous. This is the SAME game appearing twice.

For each group of duplicate rows: the earliest-posted row is kept (as the
presumed original entry), and if it doesn't already have a first_choice
value but a later duplicate does, that value is copied over before the
later row(s) are dropped. Nothing else about the kept row is touched.

Run standalone, any time:
    python3 engine/dedupe_master_history.py
"""

import shutil
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
MASTER_FILE = REPO_ROOT / "data" / "master_history_raw.csv"


def team_key(names_str):
    return frozenset(x.strip() for x in str(names_str).split("/") if x.strip())


def main():
    master = pd.read_csv(MASTER_FILE, dtype=str).fillna("")
    if "first_choice" not in master.columns:
        master["first_choice"] = ""
    master["posted_dt"] = pd.to_datetime(master["posted"], errors="coerce")
    master["day"] = master["posted_dt"].dt.strftime("%Y-%m-%d")

    def sig(row):
        t1 = team_key(row["winning_team"])
        t2 = team_key(row["losing_team"])
        return (row["day"], row["pool"], frozenset([t1, t2]), row["winning_score"], row["losing_score"])

    master["_sig"] = master.apply(sig, axis=1)

    to_drop = []
    fc_copied = 0
    groups_removed = 0
    days_affected = {}

    for _sig, idxs in master.groupby("_sig").groups.items():
        idxs = list(idxs)
        if len(idxs) < 2:
            continue
        idxs_sorted = sorted(idxs, key=lambda i: master.at[i, "posted_dt"])
        keep, dupes = idxs_sorted[0], idxs_sorted[1:]

        if not str(master.at[keep, "first_choice"]).strip():
            for d in dupes:
                fc = str(master.at[d, "first_choice"]).strip()
                if fc:
                    master.at[keep, "first_choice"] = fc
                    fc_copied += 1
                    break

        to_drop.extend(dupes)
        groups_removed += 1
        day = master.at[keep, "day"]
        days_affected[day] = days_affected.get(day, 0) + len(dupes)

    if not to_drop:
        print("No exact duplicate game rows found -- nothing to remove.")
        return

    backup_path = MASTER_FILE.with_name(
        f"master_history_raw.csv.pre-dedupe-{datetime.now():%Y%m%d-%H%M%S}.bak"
    )
    shutil.copy2(MASTER_FILE, backup_path)

    master = master.drop(index=to_drop).drop(columns=["posted_dt", "day", "_sig"])
    master.to_csv(MASTER_FILE, index=False)

    print(f"Removed {len(to_drop)} duplicate row(s) across {groups_removed} game(s) "
          f"({len(days_affected)} day(s) affected). Backup saved to {backup_path.name}.")
    print(f"  ({fc_copied} kept row(s) picked up a first_choice value from the row being removed.)")
    print("Days affected:")
    for day, n in sorted(days_affected.items()):
        print(f"  {day}: {n} duplicate row(s) removed")


if __name__ == "__main__":
    main()
