#!/usr/bin/env python3
"""
Rebuilds the full rating log under PROVISIONAL_K_START=40, PROVISIONAL_K_GAMES=60
(the values the fine-grid sweep found optimal for the provisional-window
population) and shows Jose L Valdez R and Russ Brannon's full game-by-game
trajectories under these restored parameters -- no swing cap applied --
so we can see how much of the original problem this alone resolves.

Usage:
    python3 recheck_players_restored_k.py --input ../data/master_history_raw.csv
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pickleball_engine_v2 as engine  # noqa: E402

PLAYERS_TO_CHECK = ["Jose L Valdez R", "Russ Brannon"]


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
    engine._provisional_k()."""
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

            player_rows.append(
                {
                    "match_id": match_id,
                    "posted_dt": r["posted_dt"],
                    "player": player,
                    "opp1": opp1,
                    "opp2": opp2,
                    "is_win": is_win,
                    "rating_change": round(post - pre, 2),
                    "player_pre_rating": round(pre, 2),
                    "player_post_rating": post,
                    "include_in_ratings": "Yes" if include else "No",
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


def report_player(player_log, player_name):
    sub = player_log[(player_log["player"] == player_name) & (player_log["include_in_ratings"] == "Yes")].copy()
    sub = sub.sort_values(["posted_dt", "match_id"])

    if sub.empty:
        print(f"No rated games found for '{player_name}'.")
        return

    sub["date"] = pd.to_datetime(sub["posted_dt"]).dt.date

    print(f"=== {player_name}: {len(sub)} rated games (restored K_START=40, K_GAMES=60, no cap) ===\n")

    print("--- Sessions with a swing >= 80pts ---")
    for date, g in sub.groupby("date"):
        big = g[g["rating_change"].abs() >= 80]
        if big.empty:
            continue
        print(f"{date}: net {g['rating_change'].sum():+.2f}  |  swings: {[round(x,1) for x in g['rating_change']]}")

    total_change = sub["rating_change"].sum()
    final_rating = 1000 + total_change
    max_swing = sub["rating_change"].abs().max()
    n_big_swings = (sub["rating_change"].abs() >= 80).sum()

    print()
    print(f"Final rating: {final_rating:.0f}  (net change {total_change:+.1f})")
    print(f"Largest single swing: {max_swing:.1f}")
    print(f"Games with swing >= 80pts: {n_big_swings} of {len(sub)}")
    print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()

    raw = load_raw(args.input)

    engine.PROVISIONAL_K_START = 40.0
    engine.PROVISIONAL_K_GAMES = 60

    player_log = build_full_player_log(raw)

    for player_name in PLAYERS_TO_CHECK:
        report_player(player_log, player_name)


if __name__ == "__main__":
    main()
