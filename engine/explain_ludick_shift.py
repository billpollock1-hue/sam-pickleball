#!/usr/bin/env python3
"""
Steve Ludick has 4000+ career games -- a provisional-K change should barely
move him, since it only touches his first 60-120 games out of thousands.
This rebuilds his full log under both the old (100/120) and restored (40/60)
settings and shows exactly what happened in his early record to explain
whatever difference shows up.

Usage:
    python3 explain_ludick_shift.py --input ../data/master_history_raw.csv
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pickleball_engine_v2 as engine  # noqa: E402

PLAYER = "Steve Ludick"


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
            (w1, 1, d_w1, player_game_count[w1] + 1),
            (w2, 1, d_w2, player_game_count[w2] + 1),
            (l1, 0, d_l1, player_game_count[l1] + 1),
            (l2, 0, d_l2, player_game_count[l2] + 1),
        ]

        for player, is_win, delta, game_num in rows_for_game:
            pre = snap[player]
            post = round(pre + delta, 2) if include else round(pre, 2)
            player_rows.append({
                "posted_dt": r["posted_dt"],
                "player": player,
                "is_win": is_win,
                "game_num": game_num,
                "rating_change": round(post - pre, 2),
                "player_pre_rating": round(pre, 2),
                "player_post_rating": post,
                "include_in_ratings": "Yes" if include else "No",
            })

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


def report(raw, k_start, k_games, label):
    engine.PROVISIONAL_K_START = float(k_start)
    engine.PROVISIONAL_K_GAMES = int(k_games)

    player_log = build_full_player_log(raw)
    sub = player_log[(player_log["player"] == PLAYER) & (player_log["include_in_ratings"] == "Yes")].copy()
    sub = sub.sort_values("posted_dt")

    early = sub[sub["game_num"] <= k_games]
    final_rating = sub["player_post_rating"].iloc[-1]

    print(f"--- {label} (K_START={k_start}, K_GAMES={k_games}) ---")
    print(f"Games 1-{k_games} (provisional window): {len(early)} games")
    print(f"  wins: {int(early['is_win'].sum())}, losses: {len(early) - int(early['is_win'].sum())}")
    print(f"  net rating change over provisional window: {early['rating_change'].sum():+.1f}")
    print(f"  rating at end of provisional window: {early['player_post_rating'].iloc[-1]:.0f}" if len(early) else "  (no games)")
    print(f"Final rating (all {len(sub)} career games): {final_rating:.0f}")
    print()

    return sub


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()

    raw = load_raw(args.input)

    sub_old = report(raw, 100, 120, "OLD (Step 2 values)")
    sub_new = report(raw, 40, 60, "RESTORED (reverted values)")

    print("--- Direct comparison ---")
    print(f"Final rating, OLD settings:      {sub_old['player_post_rating'].iloc[-1]:.0f}")
    print(f"Final rating, RESTORED settings: {sub_new['player_post_rating'].iloc[-1]:.0f}")
    print(f"Difference: {sub_new['player_post_rating'].iloc[-1] - sub_old['player_post_rating'].iloc[-1]:+.1f}")
    print()

    print("--- Ludick's first 10 rated games ever (both settings should show same wins/losses, different magnitudes) ---")
    print(f"{'Game#':>6} | {'Win?':>5} | {'OLD delta':>10} | {'NEW delta':>10}")
    n = min(10, len(sub_old), len(sub_new))
    for i in range(n):
        o = sub_old.iloc[i]
        nrow = sub_new.iloc[i]
        print(f"{o['game_num']:>6} | {'W' if o['is_win'] else 'L':>5} | {o['rating_change']:>10.2f} | {nrow['rating_change']:>10.2f}")


if __name__ == "__main__":
    main()
