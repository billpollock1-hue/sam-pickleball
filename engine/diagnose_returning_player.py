"""
Checks how the "coasting on old glory" scenario actually plays out for a
real returning player: someone who took a long break, then came back.

Specifically checks:
  1. What their cumulative rating looked like right before the gap
  2. Whether they'd be excluded from the active leaderboard during the gap
     (via freshness_tier -- the real safety net, not the 15%-max shrinkage)
  3. Critically: does "avg_game_age" get computed over their FULL cumulative
     history (which could keep effective_age permanently high for a
     long-tenured player, even after they resume playing regularly) or does
     it reset in some way once they're back? This determines whether the
     exclusion mechanism still works correctly if we move to pure cumulative
     Elo with no window at all.

Usage:
    cd "/Users/billpollock/Documents/SAM Pickleball/sam-pickleball/engine"
    python3 diagnose_returning_player.py --input "../data/master_history_raw.csv"
"""
import argparse
from pathlib import Path

import pandas as pd

import pickleball_engine_v2 as eng


def find_returning_players(full_player_log, min_gap_days=180, min_games_before=20, min_games_after=10):
    """Find players with a long gap in play, followed by a real return."""
    rated = full_player_log[full_player_log["include_in_ratings"] == "Yes"].copy()
    rated["posted_dt"] = pd.to_datetime(rated["posted_dt"])

    candidates = []
    for player, sub in rated.groupby("player"):
        sub = sub.sort_values("posted_dt")
        dates = sub["posted_dt"].tolist()
        if len(dates) < min_games_before + min_games_after:
            continue
        gaps = [(dates[i+1] - dates[i]).days for i in range(len(dates)-1)]
        if not gaps:
            continue
        max_gap = max(gaps)
        if max_gap < min_gap_days:
            continue
        gap_idx = gaps.index(max_gap)
        games_before = gap_idx + 1
        games_after = len(dates) - gap_idx - 1
        if games_before >= min_games_before and games_after >= min_games_after:
            candidates.append({
                "player": player,
                "max_gap_days": max_gap,
                "gap_start": dates[gap_idx],
                "gap_end": dates[gap_idx + 1],
                "games_before_gap": games_before,
                "games_after_gap": games_after,
                "total_games": len(dates),
            })

    return pd.DataFrame(candidates).sort_values("max_gap_days", ascending=False)


def trace_player_freshness(raw, full_player_log, player_name, gap_end_date, half_life=None):
    """
    Walks forward from a player's return date, checking their rating and
    freshness classification at several points using the CUMULATIVE log
    (no window) -- to see whether avg_game_age (computed over their full
    history) traps them in a permanently "stale" classification even after
    they resume playing.
    """
    rated = full_player_log[full_player_log["include_in_ratings"] == "Yes"].copy()
    rated["posted_dt"] = pd.to_datetime(rated["posted_dt"])
    player_games = rated[rated["player"] == player_name].sort_values("posted_dt")

    gap_end = pd.Timestamp(gap_end_date)
    post_gap_games = player_games[player_games["posted_dt"] >= gap_end]

    print(f"\n{'='*90}")
    print(f"Tracing {player_name} after returning from a gap ending {gap_end.date()}")
    print(f"{'='*90}")

    checkpoints = [0, 4, 9, 19, 29]  # games after return: 1st, 5th, 10th, 20th, 30th
    for n in checkpoints:
        if n >= len(post_gap_games):
            continue
        as_of = post_gap_games.iloc[n]["posted_dt"]
        as_of_ts = pd.Timestamp(as_of).normalize()

        games_up_to = rated[(rated["player"] == player_name) & (rated["posted_dt"] <= as_of_ts + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))].sort_values("posted_dt")
        rating = float(games_up_to["player_post_rating"].iloc[-1])
        last_played = pd.Timestamp(games_up_to["posted_dt"].iloc[-1]).date()
        days_since_last = int((as_of_ts.date() - last_played).days)

        game_ages_full_history = [(as_of_ts.date() - pd.Timestamp(d).date()).days for d in games_up_to["posted_dt"]]
        avg_game_age_full = round(sum(game_ages_full_history) / len(game_ages_full_history), 1)

        last60 = games_up_to.tail(eng.LAST_N_GAMES)
        game_ages_last60 = [(as_of_ts.date() - pd.Timestamp(d).date()).days for d in last60["posted_dt"]]
        avg_game_age_last60 = round(sum(game_ages_last60) / len(game_ages_last60), 1)

        tier_full = eng.freshness_tier(days_since_last, avg_game_age_full)
        tier_last60 = eng.freshness_tier(days_since_last, avg_game_age_last60)

        print(f"  Game #{n+1} after return ({as_of_ts.date()}): rating={rating:.0f}  "
              f"days_since_last={days_since_last}")
        print(f"      avg_game_age over FULL history: {avg_game_age_full} days -> tier: {tier_full}")
        print(f"      avg_game_age over last-60 only: {avg_game_age_last60} days -> tier: {tier_last60}")


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
    parser = argparse.ArgumentParser(description="Diagnose returning-player rating/freshness behavior.")
    parser.add_argument("--input", required=True, help="Path to master history CSV")
    parser.add_argument("--top-n", type=int, default=10, help="How many candidate returning players to show")
    args = parser.parse_args()

    raw = load_raw(Path(args.input))
    full_player_log = eng.build_full_player_log(raw)

    print("=" * 90)
    print("CANDIDATES: players with a long gap, then a real return")
    print("=" * 90)
    candidates = find_returning_players(full_player_log)
    print(candidates.head(args.top_n).to_string(index=False))

    if not candidates.empty:
        top = candidates.iloc[0]
        trace_player_freshness(raw, full_player_log, top["player"], top["gap_end"])


if __name__ == "__main__":
    main()
