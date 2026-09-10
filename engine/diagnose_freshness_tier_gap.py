#!/usr/bin/env python3
"""
Finds players who pass build_current_leaderboard()'s own exclusion rules
(MIN_GAMES, 182-day inactivity, membership) but still get dropped from the
actual Leaderboard sheet by the separate Freshness Tier filter
(Very Fresh/Mature only) in main(). These are cases where the newer,
last-played-date-based rule and the older, avg-game-age-based freshness
tier disagree.
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

    full_board = final.build_current_leaderboard(full_log, as_of)

    gap = full_board[~full_board["Freshness Tier"].isin(["Very Fresh", "Mature"])].copy()
    gap = gap.sort_values("Days Since Last Play")

    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 120)
    print(f"Players passing MIN_GAMES/182-day/membership rules, but dropped by Freshness Tier filter: {len(gap)}\n")
    print(gap[["Player", "Player Rating", "Days Since Last Play", "Avg Game Age", "Freshness Tier"]].to_string(index=False))


if __name__ == "__main__":
    main()
