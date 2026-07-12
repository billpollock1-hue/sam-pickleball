"""
Backfill shootout session numbers across historical data.

The 'shootout' field in master_history_raw.csv has been blank/NaN for
essentially all 13,797 historical rows (a scraper bug fixed separately
in scrape.js).

Method: Session 2 cannot structurally begin until every Session 1 game
that day has completed. So for each date, sort all games chronologically
and split by COUNT at the midpoint -- the earlier half is Session 1, the
later half is Session 2. Verified against a known-correct real example
(Apr 23, 2026): the count-based midpoint landed exactly on the true
7:01 AM / 7:13 AM session boundary.

Every play date is assumed to run exactly two sessions (per direct
confirmation), so no single-vs-split ambiguity detection is needed.
Dates with very few games (below MIN_GAMES_FOR_SPLIT) are left as a
single session, since a meaningful split isn't possible either way.

Usage:
  python3 backfill_shootout_numbers.py            # dry run, reports only
  python3 backfill_shootout_numbers.py --write     # writes the corrected CSV
"""

import sys
from pathlib import Path
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
CSV_PATH = REPO_ROOT / "data" / "master_history_raw.csv"

MIN_GAMES_FOR_SPLIT = 4


def classify_date(grp_sorted):
    n = len(grp_sorted)
    if n < MIN_GAMES_FOR_SPLIT:
        return [1] * n, "single"
    midpoint = n // 2
    labels = [1] * midpoint + [2] * (n - midpoint)
    return labels, "split"


def main():
    write_mode = "--write" in sys.argv

    df = pd.read_csv(CSV_PATH)
    df["posted_dt"] = pd.to_datetime(df["posted"], errors="coerce")
    df["play_date"] = df["posted_dt"].dt.date.astype(str)

    new_shootout = pd.Series(index=df.index, dtype="Int64")
    status_counts = {"single": 0, "split": 0}

    for play_date, grp in df.groupby("play_date"):
        grp_sorted = grp.sort_values("posted_dt")
        labels, status = classify_date(grp_sorted)
        status_counts[status] += 1
        new_shootout.loc[grp_sorted.index] = labels

    df["shootout"] = new_shootout

    print("=" * 70)
    print("BACKFILL SUMMARY")
    print("=" * 70)
    print(f"Total dates processed: {sum(status_counts.values())}")
    print(f"  Split into two sessions:                 {status_counts['split']}")
    print(f"  Single session (too few games to split):  {status_counts['single']}")
    print()
    print("Final shootout value counts:")
    print(df["shootout"].value_counts(dropna=False))
    print()

    df_out = df.drop(columns=["posted_dt", "play_date"])

    if write_mode:
        df_out.to_csv(CSV_PATH, index=False)
        print(f"WROTE corrected data to {CSV_PATH}")
    else:
        print("Dry run only -- no file written. Re-run with --write to apply.")


if __name__ == "__main__":
    main()
