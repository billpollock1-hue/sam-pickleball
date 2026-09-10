#!/usr/bin/env python3
"""
Step 2 re-check, part 2: now that PROVISIONAL_K_START=100 is confirmed to
hurt predictions in the provisional-window population it's applied to
(previous sweep), this narrows in on where the "still provisional" bucket's
Brier score actually bottoms out across a tighter (K_START x K_GAMES) grid
centered near the values that didn't show harm.

Same methodology as sweep_provisional_validation_confound.py -- MIN_GAMES
eligibility gate, bucketed by min prior-game count across the 4 players in
each scored game.

Usage:
    python3 sweep_provisional_k_finegrid.py --input ../data/master_history_raw.csv
"""

import argparse
import math
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pickleball_engine_v2 as engine  # noqa: E402


def load_raw(input_path):
    raw = pd.read_csv(input_path)
    raw.columns = [c.strip() for c in raw.columns]
    raw["posted_dt"] = pd.to_datetime(raw["posted"], errors="coerce")

    for col in ["winning_team", "losing_team"]:
        raw[col] = [engine.apply_manual_fix(engine.norm(team), dt) for team, dt in zip(raw[col], raw["posted_dt"])]

    raw = raw.drop_duplicates(
        subset=["posted_dt", "winning_team", "losing_team", "winning_score", "losing_score"]
    ).sort_values(
        ["posted_dt", "winning_team", "losing_team", "winning_score", "losing_score"]
    ).reset_index(drop=True)

    raw["exclude_match"] = raw["winning_team"].map(engine.team_has_placeholder) | raw["losing_team"].map(engine.team_has_placeholder)
    raw["include_in_ratings"] = ~raw["exclude_match"]
    return raw


def build_full_player_log(raw):
    """Exact copy of engine.build_full_player_log() -- reads
    engine.PROVISIONAL_K_START / engine.PROVISIONAL_K_GAMES via
    engine._provisional_k(), so monkey-patching those globals before
    calling this changes behavior with no other code changes needed."""
    ratings = defaultdict(lambda: engine.BASE_ELO)
    player_game_count = defaultdict(int)
    player_rows = []

    for match_id, (_, r) in enumerate(raw.iterrows(), start=1):
        w1, w2 = engine.split_team(r["winning_team"])
        l1, l2 = engine.split_team(r["losing_team"])
        sw, sl = int(r["winning_score"]), int(r["losing_score"])
        include = bool(r["include_in_ratings"])

        snap = {p: ratings[p] for p in [w1, w2, l1, l2]}
        team_win_pre = (snap[w1] + snap[w2]) / 2
        team_lose_pre = (snap[l1] + snap[l2]) / 2
        exp_win = engine.expected(team_win_pre, team_lose_pre)
        exp_lose = 1 - exp_win
        pred_win = engine.predicted(team_win_pre, team_lose_pre)
        pred_lose = 1 - pred_win
        mult = engine.margin_multiplier(sw - sl)

        if include:
            k_w1 = engine._provisional_k(player_game_count[w1] + 1)
            k_w2 = engine._provisional_k(player_game_count[w2] + 1)
            k_l1 = engine._provisional_k(player_game_count[l1] + 1)
            k_l2 = engine._provisional_k(player_game_count[l2] + 1)
        else:
            k_w1 = k_w2 = k_l1 = k_l2 = 0.0

        d_w1 = round(k_w1 * (1 - exp_win) * mult, 2)
        d_w2 = round(k_w2 * (1 - exp_win) * mult, 2)
        d_l1 = round(k_l1 * (0 - exp_lose) * mult, 2)
        d_l2 = round(k_l2 * (0 - exp_lose) * mult, 2)

        rows_for_game = [
            (w1, w2, l1, l2, 1, sw, sl, d_w1, pred_win),
            (w2, w1, l1, l2, 1, sw, sl, d_w2, pred_win),
            (l1, l2, w1, w2, 0, sl, sw, d_l1, pred_lose),
            (l2, l1, w1, w2, 0, sl, sw, d_l2, pred_lose),
        ]

        for player, partner, opp1, opp2, is_win, pf, pa, delta, exp_result in rows_for_game:
            pre = snap[player]
            post = round(pre + delta, 2) if include else round(pre, 2)
            partner_pre = snap[partner]
            opp1_pre = snap[opp1]
            opp2_pre = snap[opp2]
            own_team_pre = (pre + partner_pre) / 2
            avg_opp_pre = (opp1_pre + opp2_pre) / 2
            schedule_diff = own_team_pre - avg_opp_pre

            player_rows.append(
                {
                    "match_id": match_id,
                    "posted": r["posted_dt"].date(),
                    "posted_dt": r["posted_dt"],
                    "player": player,
                    "partner": partner,
                    "opp1": opp1,
                    "opp2": opp2,
                    "is_win": is_win,
                    "expected_win": exp_result,
                    "pf": pf,
                    "pa": pa,
                    "margin": pf - pa,
                    "player_pre_rating": round(pre, 2),
                    "player_post_rating": post,
                    "rating_change": round(post - pre, 2),
                    "partner_pre_rating": round(partner_pre, 2),
                    "avg_opponent_pre_rating": round(avg_opp_pre, 2),
                    "schedule_differential": round(schedule_diff, 2),
                    "team_pre_rating": round(team_win_pre if is_win else team_lose_pre, 2),
                    "opp_team_pre_rating": round(team_lose_pre if is_win else team_win_pre, 2),
                    "expected_result": round(exp_result, 4),
                    "include_in_ratings": "Yes" if include else "No",
                    "pool": str(r.get("pool", "") or ""),
                    "shootout": int(r["shootout"]) if pd.notna(r.get("shootout")) else 1,
                }
            )

        if include:
            ratings[w1] = round(snap[w1] + d_w1, 2)
            ratings[w2] = round(snap[w2] + d_w2, 2)
            ratings[l1] = round(snap[l1] + d_l1, 2)
            ratings[l2] = round(snap[l2] + d_l2, 2)
            player_game_count[w1] += 1
            player_game_count[w2] += 1
            player_game_count[l1] += 1
            player_game_count[l2] += 1

    return pd.DataFrame(player_rows)


def validate_by_bucket(player_log, as_of, min_prior_games):
    as_of = pd.Timestamp(as_of).normalize()
    log = player_log[
        (player_log["include_in_ratings"] == "Yes")
        & (pd.to_datetime(player_log["posted_dt"]) <= as_of + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))
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
        min_prior = min(prior_counts[p] for p in players)
        if min_prior < min_prior_games:
            for _, r in g.iterrows():
                prior_counts[r["player"]] += 1
            continue

        game_date = pd.Timestamp(g["posted_dt"].iloc[0]).date()
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

        win_team_rating = float(winners["team_pre_rating"].iloc[0])
        lose_team_rating = float(losers["team_pre_rating"].iloc[0])

        if win_team_rating >= lose_team_rating:
            favorite_rating, underdog_rating, favorite_won = win_team_rating, lose_team_rating, 1
        else:
            favorite_rating, underdog_rating, favorite_won = lose_team_rating, win_team_rating, 0

        pred_fav_win = engine.predicted(favorite_rating, underdog_rating)
        pred_fav_win = min(max(pred_fav_win, 0.001), 0.999)

        brier = (pred_fav_win - favorite_won) ** 2
        log_loss = -math.log(pred_fav_win if favorite_won else 1 - pred_fav_win)

        bucket = "still provisional" if min_prior < engine.PROVISIONAL_K_GAMES else "matured"

        eval_rows.append({"bucket": bucket, "brier": brier, "log_loss": log_loss})

        for _, r in g.iterrows():
            prior_counts[r["player"]] += 1

    if not eval_rows:
        return {}

    ev = pd.DataFrame(eval_rows)
    results = {}
    for bucket, sub in ev.groupby("bucket"):
        results[bucket] = {
            "games": len(sub),
            "brier": round(sub["brier"].mean(), 4),
            "log_loss": round(sub["log_loss"].mean(), 4),
        }
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()

    raw = load_raw(args.input)
    as_of = pd.Timestamp(raw["posted_dt"].max().date())

    k_starts = [30, 40, 50]
    k_games_options = [45, 60, 75, 90]

    print(f"MIN_GAMES gate relaxed to: {engine.MIN_GAMES}")
    print(f"{'K_START':>8} | {'K_GAMES':>8} | {'Bucket':>18} | {'Games':>6} | {'Brier':>7} | {'LogLoss':>8}")
    print("-" * 76)

    orig_start = engine.PROVISIONAL_K_START
    orig_games = engine.PROVISIONAL_K_GAMES

    best_provisional_brier = None
    best_combo = None

    for k_start in k_starts:
        for k_games in k_games_options:
            engine.PROVISIONAL_K_START = float(k_start)
            engine.PROVISIONAL_K_GAMES = int(k_games)

            player_log = build_full_player_log(raw)
            results = validate_by_bucket(player_log, as_of, min_prior_games=engine.MIN_GAMES)

            for bucket, m in sorted(results.items()):
                print(f"{k_start:>8} | {k_games:>8} | {bucket:>18} | {m['games']:>6} | {m['brier']:>7.4f} | {m['log_loss']:>8.4f}")
                if bucket == "still provisional":
                    if best_provisional_brier is None or m["brier"] < best_provisional_brier:
                        best_provisional_brier = m["brier"]
                        best_combo = (k_start, k_games)
            print()

    engine.PROVISIONAL_K_START = orig_start
    engine.PROVISIONAL_K_GAMES = orig_games

    if best_combo:
        print(f"Best 'still provisional' Brier score: {best_provisional_brier:.4f} at K_START={best_combo[0]}, K_GAMES={best_combo[1]}")


if __name__ == "__main__":
    main()
