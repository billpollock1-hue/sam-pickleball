"""
Step 2b: validates the credibility/freshness shrinkage's parameters
(MAX_FRESHNESS_PENALTY, NO_AGING_DAYS) against real outcomes -- the same
evidence-based approach used for K-factor/provisional-K/margin cap, applied
to the one mechanism that was explicitly out of scope for that earlier pass.

SCOPING NOTE: build_model_validation()'s evaluation set (games where all
four players have 60+ prior rated games) means sample_conf is always
saturated at 1.0 for every evaluated game -- so CONF_DEN cannot be
meaningfully tested here. This script tests MAX_FRESHNESS_PENALTY and
NO_AGING_DAYS only, which act on the freshness (staleness-from-a-gap) half
of the shrinkage, not the sample-size half.

Method: for each qualifying 2026 game, computes each team's rating TWO ways
-- raw (no shrinkage) and shrunk (using a candidate MAX_FRESHNESS_PENALTY /
NO_AGING_DAYS pair, applied via each player's own last-60-game freshness
window, exactly as build_player_freshness_window will in the real fix) --
then checks which produces better-calibrated predictions of the actual
outcome.

Usage:
    cd "/Users/billpollock/Documents/SAM Pickleball/sam-pickleball/engine"
    python3 validate_freshness_shrinkage.py --input "../data/master_history_raw.csv"
"""
import argparse
import math
from pathlib import Path
from collections import defaultdict

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


def freshness_factor_custom(days_since_last_play, avg_game_age, no_aging_days, max_penalty):
    last_play_penalty = max(0, days_since_last_play - no_aging_days) / 365
    avg_age_penalty = max(0, avg_game_age - no_aging_days) / 365
    total_penalty = min(max_penalty, last_play_penalty * 0.60 + avg_age_penalty * 0.40)
    return 1.0 - total_penalty


def shrunk_rating(full_player_log, player, as_of, raw_rating, no_aging_days, max_penalty, window_size=120):
    rated = full_player_log[
        (full_player_log["include_in_ratings"] == "Yes")
        & (full_player_log["player"] == player)
        & (pd.to_datetime(full_player_log["posted_dt"]) <= as_of + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))
    ].sort_values(["posted_dt", "match_id"])
    window = rated.tail(window_size)
    if window.empty:
        return raw_rating

    last_played = pd.Timestamp(window["posted_dt"].iloc[-1]).date()
    days_since_last = int((as_of.date() - last_played).days)
    game_ages = [(as_of.date() - pd.Timestamp(d).date()).days for d in window["posted_dt"]]
    avg_game_age = sum(game_ages) / len(game_ages)

    fresh_conf = freshness_factor_custom(days_since_last, avg_game_age, no_aging_days, max_penalty)
    return 1000 + (raw_rating - 1000) * fresh_conf


def run_validation(raw, as_of, no_aging_days, max_penalty, use_shrinkage=True):
    full_player_log = eng.build_full_player_log(raw)
    log = full_player_log[
        (full_player_log["include_in_ratings"] == "Yes")
        & (pd.to_datetime(full_player_log["posted_dt"]) <= pd.Timestamp(as_of) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))
    ].copy()
    log = log.sort_values(["posted_dt", "match_id", "player"])

    prior_counts = defaultdict(int)
    eval_rows = []

    for match_id, g in log.groupby("match_id", sort=True):
        if len(g) != 4:
            for _, r in g.iterrows():
                prior_counts[r["player"]] += 1
            continue
        players = g["player"].tolist()
        if not all(prior_counts[p] >= 60 for p in players):
            for _, r in g.iterrows():
                prior_counts[r["player"]] += 1
            continue
        game_date = pd.Timestamp(g["posted_dt"].iloc[0])
        if game_date.year != 2026:
            for _, r in g.iterrows():
                prior_counts[r["player"]] += 1
            continue

        winners = g[g["is_win"] == 1]
        losers = g[g["is_win"] == 0]
        if len(winners) != 2 or len(losers) != 2:
            for _, r in g.iterrows():
                prior_counts[r["player"]] += 1
            continue

        if use_shrinkage:
            w_ratings = [
                shrunk_rating(full_player_log, p, game_date, float(rr), no_aging_days, max_penalty)
                for p, rr in zip(winners["player"], winners["team_pre_rating"])
            ]
            l_ratings = [
                shrunk_rating(full_player_log, p, game_date, float(rr), no_aging_days, max_penalty)
                for p, rr in zip(losers["player"], losers["team_pre_rating"])
            ]
            win_team_rating = sum(w_ratings) / 2
            lose_team_rating = sum(l_ratings) / 2
        else:
            win_team_rating = float(winners["team_pre_rating"].iloc[0])
            lose_team_rating = float(losers["team_pre_rating"].iloc[0])

        if win_team_rating >= lose_team_rating:
            favorite_rating, underdog_rating, favorite_won = win_team_rating, lose_team_rating, 1
        else:
            favorite_rating, underdog_rating, favorite_won = lose_team_rating, win_team_rating, 0

        pred_fav_win = min(max(eng.predicted(favorite_rating, underdog_rating), 0.001), 0.999)
        brier = (pred_fav_win - favorite_won) ** 2
        log_loss = -math.log(pred_fav_win if favorite_won else 1 - pred_fav_win)
        eval_rows.append({"brier": brier, "log_loss": log_loss})

        for _, r in g.iterrows():
            prior_counts[r["player"]] += 1

    if not eval_rows:
        return None, None
    ev = pd.DataFrame(eval_rows)
    return ev["brier"].mean(), ev["log_loss"].mean()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--as-of", default=None)
    args = parser.parse_args()

    raw = load_raw(Path(args.input))
    as_of = pd.Timestamp(args.as_of or raw["posted_dt"].max().date())

    print(f"Freshness-shrinkage validation -- as of {as_of.date()}")
    print("(K_FACTOR=20, PROVISIONAL_K_START=100, PROVISIONAL_K_GAMES=120, margin uncapped -- locked from Steps 1-2)\n")

    print("=" * 80)
    print("BASELINE: no shrinkage at all (raw cumulative rating, unadjusted)")
    print("=" * 80)
    brier0, ll0 = run_validation(raw, as_of, no_aging_days=90, max_penalty=0.0, use_shrinkage=False)
    print(f"  Brier={brier0:.4f}   Log Loss={ll0:.4f}\n")

    print("=" * 80)
    print("SWEEP: MAX_FRESHNESS_PENALTY  [current = 0.15]  (holding NO_AGING_DAYS=90)")
    print("=" * 80)
    for mp in [0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50, 1.0]:
        brier, ll = run_validation(raw, as_of, no_aging_days=90, max_penalty=mp, use_shrinkage=True)
        marker = "  <-- current" if abs(mp - 0.15) < 0.001 else ""
        print(f"  MAX_FRESHNESS_PENALTY={mp:<6} Brier={brier:.4f}   Log Loss={ll:.4f}{marker}")

    print("\n" + "=" * 80)
    print("SWEEP: NO_AGING_DAYS  [current = 90]  (holding MAX_FRESHNESS_PENALTY=0.15)")
    print("=" * 80)
    for nad in [30, 60, 90, 120, 180, 270, 365]:
        brier, ll = run_validation(raw, as_of, no_aging_days=nad, max_penalty=0.15, use_shrinkage=True)
        marker = "  <-- current" if nad == 90 else ""
        print(f"  NO_AGING_DAYS={nad:<6} Brier={brier:.4f}   Log Loss={ll:.4f}{marker}")

    print("\nNOTE: CONF_DEN (sample-size half of shrinkage) could not be tested here --")
    print("this evaluation set requires 60+ prior games per player, so sample_conf is")
    print("always saturated at 1.0 for everyone evaluated. Would need a separate")
    print("evaluation set (including newer players) to test meaningfully.")


if __name__ == "__main__":
    main()
