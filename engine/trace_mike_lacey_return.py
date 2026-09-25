"""
Corrected trace: uses Mike Lacey's actual real play dates after his return
(not arbitrary game-count checkpoints), and computes days_since_last_play
correctly (relative to his PRIOR real play date, not the same date as the
checkpoint itself -- that was the bug in the earlier version).

Usage:
    cd "/Users/billpollock/Documents/SAM Pickleball/sam-pickleball/engine"
    python3 trace_mike_lacey_return.py --input "../data/master_history_raw.csv"
"""
import argparse
from pathlib import Path

import pandas as pd

import pickleball_engine_v2 as eng


def load_raw(input_path):
    raw = pd.read_csv(input_path)
    raw.columns = [c.strip() for c in raw.columns]
    raw["posted_dt"] = pd.to_datetime(raw["posted"], errors="coerce")
    for col in ["winning_team", "losing_team"]:
        raw[col] = [eng.apply_manual_fix(eng.norm(team), dt) for team, dt in zip(raw[col], raw["posted_dt"])]
    raw = raw.drop_duplicates(
        subset=["posted_dt", "winning_team", "losing_team", "winning_score", "losing_score"]
    ).sort_values(
        ["posted_dt", "winning_team", "losing_team", "winning_score", "losing_score"]
    ).reset_index(drop=True)
    raw["exclude_match"] = raw["winning_team"].map(eng.team_has_placeholder) | raw["losing_team"].map(eng.team_has_placeholder)
    raw["include_in_ratings"] = ~raw["exclude_match"]
    return raw


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--player", default="Mike Lacey")
    args = parser.parse_args()

    raw = load_raw(Path(args.input))
    full_player_log = eng.build_full_player_log(raw)
    rated = full_player_log[full_player_log["include_in_ratings"] == "Yes"].copy()
    rated["posted_dt"] = pd.to_datetime(rated["posted_dt"])

    sub = rated[rated["player"] == args.player].sort_values("posted_dt")
    unique_dates = sorted(sub["posted_dt"].dt.date.unique())

    print(f"{args.player} -- {len(unique_dates)} total unique play dates")
    print(f"{'='*100}")
    print(f"{'Date':<14}{'Rating (end of day)':<22}{'Real days since prior play':<28}"
          f"{'Avg age (FULL hist)':<22}{'Tier (full)':<14}{'Avg age (last-60)':<20}{'Tier (last-60)'}")
    print("-" * 140)

    prior_date = None
    for d in unique_dates:
        games_up_to = rated[
            (rated["player"] == args.player)
            & (rated["posted_dt"].dt.date <= d)
        ].sort_values("posted_dt")
        rating = float(games_up_to["player_post_rating"].iloc[-1])

        real_days_since = (d - prior_date).days if prior_date else None

        game_ages_full = [(d - pd.Timestamp(gd).date()).days for gd in games_up_to["posted_dt"]]
        avg_age_full = round(sum(game_ages_full) / len(game_ages_full), 1)

        last60 = games_up_to.tail(eng.LAST_N_GAMES)
        game_ages_60 = [(d - pd.Timestamp(gd).date()).days for gd in last60["posted_dt"]]
        avg_age_60 = round(sum(game_ages_60) / len(game_ages_60), 1)

        # days_since_last_play for tier purposes: 0 on the day itself
        tier_full = eng.freshness_tier(0, avg_age_full)
        tier_60 = eng.freshness_tier(0, avg_age_60)

        real_days_str = str(real_days_since) if real_days_since is not None else "(first in this stretch)"
        print(f"{str(d):<14}{rating:<22.0f}{real_days_str:<28}"
              f"{avg_age_full:<22}{tier_full:<14}{avg_age_60:<20}{tier_60}")

        prior_date = d


if __name__ == "__main__":
    main()
