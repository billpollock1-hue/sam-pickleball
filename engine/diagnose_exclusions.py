#!/usr/bin/env python3
"""
Tags each player who dropped off the leaderboard with the specific reason:
MIN_GAMES (not enough games in their last-60 window), INACTIVE (>182 days
since last play), or NOT_MEMBER (missing from the current DEN membership
snapshot). Uses the final engine's own real functions/constants -- no
reimplemented logic.

Usage:
    python3 diagnose_exclusions.py --input ../data/master_history_raw.csv
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pickleball_engine_v2 as final


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()

    raw = pd.read_csv(args.input)
    raw.columns = [c.strip() for c in raw.columns]
    raw["posted_dt"] = pd.to_datetime(raw["posted"], errors="coerce")

    for col in ["winning_team", "losing_team"]:
        raw[col] = [final.apply_manual_fix(final.norm(team), dt) for team, dt in zip(raw[col], raw["posted_dt"])]

    raw = raw.drop_duplicates(
        subset=["posted_dt", "winning_team", "losing_team", "winning_score", "losing_score"]
    ).sort_values(
        ["posted_dt", "winning_team", "losing_team", "winning_score", "losing_score"]
    ).reset_index(drop=True)

    raw["exclude_match"] = raw["winning_team"].map(final.team_has_placeholder) | raw["losing_team"].map(final.team_has_placeholder)
    raw["include_in_ratings"] = ~raw["exclude_match"]

    full_log = final.build_full_player_log(raw)
    as_of = pd.Timestamp(raw["posted_dt"].max().date())

    rated = full_log[
        (full_log["include_in_ratings"] == "Yes")
        & (pd.to_datetime(full_log["posted_dt"]) <= as_of + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))
    ].copy()

    current_members = final.load_current_members()
    if current_members is None:
        print("NOTE: membership file not found/unreadable -- NOT_MEMBER exclusions will not be detected this run.\n")

    rows = []
    for p in sorted(rated["player"].dropna().unique()):
        window = final.build_player_freshness_window(full_log, as_of, p)
        g = len(window)

        reason = None
        if g < final.MIN_GAMES:
            reason = "MIN_GAMES"
        else:
            player_all = rated[rated["player"] == p].sort_values(["posted_dt", "match_id"])
            last_played = player_all["posted_dt"].max()
            days_inactive = (as_of - pd.Timestamp(last_played).normalize()).days
            if days_inactive > 182:
                reason = f"INACTIVE ({days_inactive}d)"
            elif current_members is not None and p.strip() not in current_members:
                reason = "NOT_MEMBER"

        if reason:
            rows.append({"Player": p, "Reason": reason})

    df = pd.DataFrame(rows)
    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 100)
    print(f"Total excluded: {len(df)}\n")
    print(df.to_string(index=False))
    print("\nBreakdown by reason:")
    print(df["Reason"].str.replace(r"\(.*\)", "", regex=True).str.strip().value_counts())


if __name__ == "__main__":
    main()
