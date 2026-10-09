"""
One-off correlation for master_history_raw.csv dates that were manually
re-dated at some point (to correct something), such that Den's own site no
longer agrees the games happened on that calendar date at all.

Discovered case: 2026-04-28 and 2026-04-29, plus part of what's filed as
2026-04-30, don't exist under those dates on Den's site. Den shows all 72
of those games filed under a single date -- "April 30, 2026" -- as six
sessions (8:28, 8:36, 8:52, 9:04, 9:19, 9:53 AM). Confirmed two ways:
rosters in master_history_raw.csv for 04-28/04-29/04-30 line up exactly
with those six Den sessions' rosters, and archive/fc_analysis's completely
separate, months-earlier scrape of Den's site (fc_backfill.py, run in July)
independently found the same six April-30 sessions and nothing on 4/28 or
4/29.

Because of that, engine/apply_backfill.py's normal (play_date, pool)
grouping can never match these rows -- it looks for Den data dated 4/28 or
4/29 and finds none, and for 4/30 finds a different subset of the day's
games than what's actually recorded under that date in the file.

REDATE_GROUPS says, for a given batch of master_history_raw.csv dates:
"Den's site actually filed all of this under a different single date --
look there instead." Correlation happens in two passes:

  1. Positional (same approach as apply_backfill.py's fill_first_choice()):
     within each pool, master rows (across the whole group of re-dated
     master dates) are sorted by posted time, backfill rows (from the one
     real Den date) are sorted by (session order, match_index), paired up
     positionally, and trusted only if the score pair actually matches.

  2. Roster fallback: master_history_raw.csv's "posted" timestamps are
     minute-precision, so two games in the same round posted in the same
     minute can tie and land in the "wrong" relative order -- which makes
     the positional pass compare a master row against its neighbor's
     backfill row instead of its own, and fail the score check for BOTH,
     even though the data for both games is sitting right there. For
     anything still blank after pass 1, this pass searches every backfill
     row in that pool for one whose two teams (by abbreviated name) and
     score exactly match the master row, independent of position. If the
     match to a single backfill row isn't unique, or Den shows a
     different name for one of the players entirely (seen once already --
     Den's UI has labeled a drop-in/guest player "D Tryout" where the
     history file has since recorded the actual person), it's left blank
     rather than guessed.

first_choice is only ever filled in where currently blank -- neither pass
overwrites anything already there.

If you find another block of dates with this same problem, add another
entry to REDATE_GROUPS below and re-run.

Run after scraper/backfill_view_event.js has scraped the Den-side date:
    node scraper/backfill_view_event.js --start 043026 --end 043026 --only-dates 2026-04-30
    python3 engine/apply_backfill_redated.py
"""

import shutil
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
MASTER_FILE = REPO_ROOT / "data" / "master_history_raw.csv"
BACKFILL_MATCHES_FILE = REPO_ROOT / "data" / "backfill_matches.csv"

# Each group: a set of master_history_raw.csv dates that were re-dated away
# from what Den's site actually shows, and the single Den-side date to
# correlate all of them against instead.
REDATE_GROUPS = [
    {
        "master_dates": ["2026-04-28", "2026-04-29", "2026-04-30"],
        "den_date": "2026-04-30",
    },
    {
        # Confirmed by Bill: a score correction was made after the fact on
        # Den's side for the night of 2/12, which is why Den now files that
        # shootout (and, it turns out, part of 2/11's games too) under 2/13
        # instead. master_history_raw.csv's 2/11, 2/12, and 2/13 dates are
        # the correct, original ones -- Den's own date for this one is
        # what's wrong.
        "master_dates": ["2026-02-11", "2026-02-12", "2026-02-13"],
        "den_date": "2026-02-13",
    },
]


def norm_shootout(x):
    try:
        return str(int(float(x)))
    except (TypeError, ValueError):
        return str(x).strip()


def abbrev(full_name):
    parts = str(full_name).strip().split()
    if len(parts) < 2:
        return str(full_name).strip()
    return parts[0][0] + " " + " ".join(parts[1:])


def team_set(names_str, sep):
    return frozenset(x.strip() for x in str(names_str).split(sep) if x.strip())


# Den labels a drop-in/guest player generically instead of by name; the
# history file has since recorded who it actually was. Confirmed by Bill:
# the 2026-04-28/29/30 re-dated block's "D Tryout" was Chaim McKee.
NAME_ALIASES = {
    "D Tryout": "C McKee",
}


def resolve_alias(abbrev_name):
    return NAME_ALIASES.get(abbrev_name, abbrev_name)


def team_set_aliased(names_str, sep):
    return frozenset(resolve_alias(x.strip()) for x in str(names_str).split(sep) if x.strip())


def try_fill(master, idx, fc_team, team1, team2, team1_score, team2_score, win_score):
    """Shared FC-assignment logic once a game is confirmed matched. Returns
    True if first_choice was written."""
    fc_team = str(fc_team or "").strip()
    if not fc_team:
        return False  # no FC badge visible on either row for this game -- leave blank
    fc_is_winner = (
        int(team1_score) == win_score and fc_team == str(team1).strip()
    ) or (
        int(team2_score) == win_score and fc_team == str(team2).strip()
    )
    master.at[idx, "first_choice"] = (
        master.at[idx, "winning_team"] if fc_is_winner else master.at[idx, "losing_team"]
    )
    return True


def main():
    if not BACKFILL_MATCHES_FILE.exists():
        print("No data/backfill_matches.csv found -- nothing to correlate. "
              "Run scraper/backfill_view_event.js for the Den-side date(s) first.")
        return

    matches = pd.read_csv(BACKFILL_MATCHES_FILE, dtype=str).fillna("")
    if matches.empty:
        print("data/backfill_matches.csv is empty -- nothing to correlate.")
        return
    matches["shootout_sort"] = matches["shootout"].map(
        lambda x: int(x) if str(x).lstrip("-").isdigit() else 0
    )
    matches["match_index"] = pd.to_numeric(matches["match_index"], errors="coerce")

    master = pd.read_csv(MASTER_FILE, dtype=str).fillna("")
    if "first_choice" not in master.columns:
        master["first_choice"] = ""
    master["posted_dt"] = pd.to_datetime(master["posted"], errors="coerce")
    master["play_date"] = master["posted_dt"].dt.strftime("%Y-%m-%d")

    total_positional = 0
    total_fallback = 0
    total_no_backfill = 0
    total_count_mismatch_pools = 0
    total_unresolved = 0

    for group in REDATE_GROUPS:
        master_dates = group["master_dates"]
        den_date = group["den_date"]
        print(f"--- Re-dated group: master dates {master_dates} <- Den's \"{den_date}\" ---")

        den_rows = matches[matches["play_date"] == den_date]
        if den_rows.empty:
            print(f"  No data/backfill_matches.csv rows for Den date {den_date} -- "
                  f"scrape it first (see module docstring). Skipping this group.")
            continue

        group_mask = master["play_date"].isin(master_dates)
        pools = sorted(set(master.loc[group_mask, "pool"]) | set(den_rows["pool"]))

        group_positional = 0
        group_fallback = 0
        group_unresolved = 0
        for pool in pools:
            master_idx = (
                master[group_mask & (master["pool"] == pool)]
                .sort_values("posted_dt")
                .index.tolist()
            )
            backfill_rows = (
                den_rows[den_rows["pool"] == pool]
                .sort_values(["shootout_sort", "match_index"])
                .to_dict("records")
            )

            if not master_idx or not backfill_rows:
                total_no_backfill += len(backfill_rows)
                continue
            if len(master_idx) != len(backfill_rows):
                total_count_mismatch_pools += 1
                print(f"  ⚠ {pool}: {len(master_idx)} master row(s) across {master_dates} "
                      f"vs {len(backfill_rows)} Den row(s) on {den_date} -- counts don't match, "
                      f"pairing the first {min(len(master_idx), len(backfill_rows))} anyway.")

            # --- Pass 1: positional, same as apply_backfill.py ---
            n = min(len(master_idx), len(backfill_rows))
            for i in range(n):
                idx = master_idx[i]
                b = backfill_rows[i]
                if str(master.at[idx, "first_choice"]).strip():
                    continue

                try:
                    win_score = int(float(master.at[idx, "winning_score"]))
                    lose_score = int(float(master.at[idx, "losing_score"]))
                    b_scores = sorted([int(b["team1_score"]), int(b["team2_score"])], reverse=True)
                except (TypeError, ValueError):
                    continue

                if b_scores != [win_score, lose_score]:
                    continue  # left for the roster-fallback pass below

                if try_fill(master, idx, b.get("first_choice_team", ""),
                            b["team1"], b["team2"], b["team1_score"], b["team2_score"], win_score):
                    group_positional += 1

            # --- Pass 2: roster fallback for whatever's still blank ---
            still_blank = [idx for idx in master_idx if not str(master.at[idx, "first_choice"]).strip()]
            for idx in still_blank:
                try:
                    win_score = int(float(master.at[idx, "winning_score"]))
                    lose_score = int(float(master.at[idx, "losing_score"]))
                except (TypeError, ValueError):
                    group_unresolved += 1
                    continue

                w_team = team_set(master.at[idx, "winning_team"], " / ")
                l_team = team_set(master.at[idx, "losing_team"], " / ")
                w_abbrev = frozenset(abbrev(n) for n in w_team)
                l_abbrev = frozenset(abbrev(n) for n in l_team)

                candidates = []
                for b in backfill_rows:
                    bt1 = team_set_aliased(b["team1"], "/")
                    bt2 = team_set_aliased(b["team2"], "/")
                    if {bt1, bt2} != {w_abbrev, l_abbrev}:
                        continue
                    try:
                        b1s, b2s = int(b["team1_score"]), int(b["team2_score"])
                    except (TypeError, ValueError):
                        continue
                    if {b1s, b2s} != {win_score, lose_score}:
                        continue
                    # Confirm each team's score lines up with the same team,
                    # not just that the two scores appear somewhere.
                    if (bt1 == w_abbrev and b1s == win_score) or (bt1 == l_abbrev and b1s == lose_score):
                        candidates.append(b)

                if len(candidates) == 1:
                    b = candidates[0]
                    if try_fill(master, idx, b.get("first_choice_team", ""),
                                b["team1"], b["team2"], b["team1_score"], b["team2_score"], win_score):
                        group_fallback += 1
                    # else: FC badge wasn't visible on either row -- leave blank, not unresolved
                else:
                    group_unresolved += 1  # zero or ambiguous (>1) roster matches on Den's side

        print(f"  positional: filled {group_positional}. roster fallback: filled {group_fallback}. "
              f"unresolved: {group_unresolved}.")
        total_positional += group_positional
        total_fallback += group_fallback
        total_unresolved += group_unresolved

    master = master.drop(columns=["posted_dt", "play_date"])
    total_updated = total_positional + total_fallback

    if total_updated == 0:
        print("first_choice: no rows updated (nothing new matched).")
    else:
        backup_path = MASTER_FILE.with_name(
            f"master_history_raw.csv.pre-redate-backfill-{datetime.now():%Y%m%d-%H%M%S}.bak"
        )
        shutil.copy2(MASTER_FILE, backup_path)
        master.to_csv(MASTER_FILE, index=False)
        print(f"master_history_raw.csv: filled in first_choice on {total_updated} row(s) total "
              f"({total_positional} positional + {total_fallback} roster fallback). "
              f"Backup saved to {backup_path.name}.")

    if total_no_backfill:
        print(f"  ({total_no_backfill} Den-side game(s) had no matching pool in master_history_raw.csv -- skipped.)")
    if total_unresolved:
        print(f"  ({total_unresolved} game(s) had no unique roster+score match on Den's side -- "
              f"left blank rather than guessed; check for a Den-side name substitution like 'D Tryout'.)")
    if total_count_mismatch_pools:
        print(f"  ({total_count_mismatch_pools} pool(s) had a master/Den row-count mismatch -- see warnings above.)")


if __name__ == "__main__":
    main()
