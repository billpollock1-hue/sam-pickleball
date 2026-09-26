"""
Applies the output of scraper/backfill_view_event.js to the real data files:

  1. Merges data/backfill_standings.csv into data/pool_standings.csv (same
     validation as merge_csv.py's merge_pool_standings: a pool's rows only
     land if its ranks form a clean 1..N sequence).
  2. Fills in first_choice on the matching, already-existing rows in
     data/master_history_raw.csv, using data/backfill_matches.csv.

Backfill correlation works the same way as the live path
(view_event_lib.js's correlateFirstChoice): within a (play_date, shootout,
pool) group, master rows are sorted by posted time and backfill matches by
match_index, paired up positionally, and only trusted if the score pair
actually lines up. Only rows whose first_choice is currently blank are
touched -- this never overwrites anything the live scraper already filled
in.

Run after scraper/backfill_view_event.js:
    python3 engine/apply_backfill.py
"""

import shutil
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
MASTER_FILE = REPO_ROOT / "data" / "master_history_raw.csv"
POOL_STANDINGS_FILE = REPO_ROOT / "data" / "pool_standings.csv"
BACKFILL_STANDINGS_FILE = REPO_ROOT / "data" / "backfill_standings.csv"
BACKFILL_MATCHES_FILE = REPO_ROOT / "data" / "backfill_matches.csv"


def norm_shootout(x):
    try:
        return str(int(float(x)))
    except (TypeError, ValueError):
        return str(x).strip()


def merge_standings():
    if not BACKFILL_STANDINGS_FILE.exists():
        print("No data/backfill_standings.csv found -- nothing to merge into pool_standings.csv.")
        return

    new_standings = pd.read_csv(BACKFILL_STANDINGS_FILE)
    if new_standings.empty:
        print("data/backfill_standings.csv is empty -- nothing to merge.")
        return
    new_standings["shootout"] = new_standings["shootout"].map(norm_shootout)

    if POOL_STANDINGS_FILE.exists():
        existing = pd.read_csv(POOL_STANDINGS_FILE)
        existing["shootout"] = existing["shootout"].map(norm_shootout)
    else:
        existing = pd.DataFrame(columns=["play_date", "shootout", "pool", "rank", "player", "wins", "losses", "diff"])

    group_cols = ["play_date", "shootout", "pool"]
    valid_groups = []
    for key, grp in new_standings.groupby(group_cols):
        ranks = sorted(grp["rank"].tolist())
        if ranks == list(range(1, len(ranks) + 1)):
            valid_groups.append(key)
        else:
            print(f"  ⚠ Skipping backfilled standings for {key[0]} shootout {key[1]} {key[2]}: "
                  f"ranks {ranks} are not a clean 1..N sequence.")

    if not valid_groups:
        print("No valid backfilled pool(s) to merge.")
        return

    valid_mask = new_standings.set_index(group_cols).index.isin(valid_groups)
    new_standings = new_standings[valid_mask]

    touched = set(new_standings[group_cols].itertuples(index=False, name=None))
    if not existing.empty:
        keep_mask = ~existing[group_cols].apply(tuple, axis=1).isin(touched)
        existing = existing[keep_mask]

    combined = pd.concat([existing, new_standings], ignore_index=True)
    combined = combined.sort_values(["play_date", "shootout", "pool", "rank"]).reset_index(drop=True)
    combined.to_csv(POOL_STANDINGS_FILE, index=False)
    print(f"pool_standings.csv: merged {len(new_standings)} row(s) across {len(valid_groups)} pool(s).")


def fill_first_choice():
    if not BACKFILL_MATCHES_FILE.exists():
        print("No data/backfill_matches.csv found -- nothing to fill in on master_history_raw.csv.")
        return

    matches = pd.read_csv(BACKFILL_MATCHES_FILE)
    if matches.empty:
        print("data/backfill_matches.csv is empty -- nothing to fill in.")
        return
    matches["shootout"] = matches["shootout"].map(norm_shootout)

    master = pd.read_csv(MASTER_FILE, dtype=str).fillna("")
    if "first_choice" not in master.columns:
        master["first_choice"] = ""
    master["posted_dt"] = pd.to_datetime(master["posted"], errors="coerce")
    master["play_date"] = master["posted_dt"].dt.strftime("%Y-%m-%d")
    master["shootout_norm"] = master["shootout"].map(norm_shootout)

    updated = 0
    no_master_rows = 0
    score_mismatches = 0

    for (play_date, shootout, pool), grp in matches.groupby(["play_date", "shootout", "pool"]):
        mask = (
            (master["play_date"] == play_date)
            & (master["shootout_norm"] == shootout)
            & (master["pool"] == pool)
        )
        master_idx = master[mask].sort_values("posted_dt").index.tolist()
        if not master_idx:
            no_master_rows += len(grp)
            continue

        backfill_rows = grp.sort_values("match_index").to_dict("records")
        n = min(len(master_idx), len(backfill_rows))

        for i in range(n):
            idx = master_idx[i]
            b = backfill_rows[i]
            if str(master.at[idx, "first_choice"]).strip():
                continue  # never overwrite something the live scraper already filled in

            try:
                win_score = int(float(master.at[idx, "winning_score"]))
                lose_score = int(float(master.at[idx, "losing_score"]))
                b_scores = sorted([int(b["team1_score"]), int(b["team2_score"])], reverse=True)
            except (TypeError, ValueError):
                score_mismatches += 1
                continue

            if b_scores != [win_score, lose_score]:
                score_mismatches += 1
                continue

            fc_team = str(b.get("first_choice_team", "") or "").strip()
            if not fc_team:
                continue  # no FC badge visible on either row for this game -- leave blank

            fc_is_winner = int(b["team1_score"]) == win_score and fc_team == str(b["team1"]).strip() or \
                           int(b["team2_score"]) == win_score and fc_team == str(b["team2"]).strip()
            master.at[idx, "first_choice"] = master.at[idx, "winning_team"] if fc_is_winner else master.at[idx, "losing_team"]
            updated += 1

    master = master.drop(columns=["posted_dt", "play_date", "shootout_norm"])

    if updated == 0:
        print("first_choice: no rows updated (nothing new matched).")
    else:
        backup_path = MASTER_FILE.with_name(f"master_history_raw.csv.pre-backfill-{datetime.now():%Y%m%d-%H%M%S}.bak")
        shutil.copy2(MASTER_FILE, backup_path)
        master.to_csv(MASTER_FILE, index=False)
        print(f"master_history_raw.csv: filled in first_choice on {updated} row(s). Backup saved to {backup_path.name}.")

    if no_master_rows:
        print(f"  ({no_master_rows} backfilled game(s) had no matching pool in master_history_raw.csv -- skipped.)")
    if score_mismatches:
        print(f"  ({score_mismatches} backfilled game(s) didn't line up on score -- left untouched rather than guessed.)")


if __name__ == "__main__":
    merge_standings()
    fill_first_choice()
