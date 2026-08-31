#!/usr/bin/env python3
"""
Step 2b-2 sweep: tests a per-player swing cap during the provisional-K window
against BOTH objectives -- Brier score (what Step 2 optimized) and a new
stability metric (what Step 2 never measured, and what the Valdez case
exposed as a blind spot).

Reuses the real engine's helper functions (norm, apply_manual_fix,
team_has_placeholder, expected, predicted, _provisional_k, split_team,
build_model_validation) for exact parity -- only build_full_player_log is
reimplemented locally, with one addition: an optional cap on the absolute
per-player rating delta, applied only while that player is still inside
their own provisional window (player_game_count < PROVISIONAL_K_GAMES).

Usage: place in the engine/ folder (next to pickleball_engine_v2.py) and run:
    python3 sweep_provisional_stability.py --input ../data/master_history_raw.csv
"""

import argparse
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


def build_full_player_log_capped(raw, provisional_swing_cap=None):
    """
    Exact copy of engine.build_full_player_log(), field-for-field, with one
    addition: if provisional_swing_cap is not None, any player's delta is
    clamped to +/- provisional_swing_cap while player_game_count[player] is
    still below PROVISIONAL_K_GAMES. None reproduces the current engine
    exactly (no cap) -- used as this sweep's own baseline row.
    """
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

        # --- swing cap insertion: only difference from the real engine ---
        if provisional_swing_cap is not None and include:
            if player_game_count[w1] < engine.PROVISIONAL_K_GAMES:
                d_w1 = max(-provisional_swing_cap, min(provisional_swing_cap, d_w1))
            if player_game_count[w2] < engine.PROVISIONAL_K_GAMES:
                d_w2 = max(-provisional_swing_cap, min(provisional_swing_cap, d_w2))
            if player_game_count[l1] < engine.PROVISIONAL_K_GAMES:
                d_l1 = max(-provisional_swing_cap, min(provisional_swing_cap, d_l1))
            if player_game_count[l2] < engine.PROVISIONAL_K_GAMES:
                d_l2 = max(-provisional_swing_cap, min(provisional_swing_cap, d_l2))
        # --- end insertion ---

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


def stability_metrics(player_log):
    """
    For every player, look ONLY at their own first PROVISIONAL_K_GAMES rated
    games (the window Step 2's validation never scored) and measure how
    volatile their trajectory was there.
    """
    rated = player_log[player_log["include_in_ratings"] == "Yes"].copy()
    rated = rated.sort_values(["player", "posted_dt", "match_id"])

    big_swing_players = 0
    total_players = 0
    max_swings = []

    for player, sub in rated.groupby("player"):
        window = sub.head(engine.PROVISIONAL_K_GAMES)
        if len(window) < engine.MIN_GAMES:
            continue
        total_players += 1
        max_swing = window["rating_change"].abs().max()
        max_swings.append(max_swing)
        if (window["rating_change"].abs() >= 80).sum() >= 2:
            big_swing_players += 1

    return {
        "players_evaluated": total_players,
        "players_with_2plus_80pt_swings": big_swing_players,
        "pct_with_2plus_80pt_swings": round(100 * big_swing_players / total_players, 1) if total_players else None,
        "avg_max_swing_in_provisional_window": round(sum(max_swings) / len(max_swings), 1) if max_swings else None,
        "p90_max_swing_in_provisional_window": round(pd.Series(max_swings).quantile(0.90), 1) if max_swings else None,
    }


def brier_metrics(player_log, as_of):
    validation = engine.build_model_validation(player_log, as_of)
    if validation.empty:
        return {"brier": None, "log_loss": None}
    overall = validation[validation["Section"] == "Overall"]
    if overall.empty:
        return {"brier": None, "log_loss": None}
    return {
        "brier": float(overall["Brier Score"].iloc[0]),
        "log_loss": float(overall["Log Loss"].iloc[0]),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()

    raw = load_raw(args.input)
    as_of = pd.Timestamp(raw["posted_dt"].max().date())

    swing_caps = [None, 120, 100, 80, 60, 40]

    print(f"{'Swing Cap':>10} | {'Brier':>7} | {'LogLoss':>8} | {'Players':>8} | {'2+ swings':>10} | {'% affected':>11} | {'Avg Max':>8} | {'P90 Max':>8}")
    print("-" * 100)

    for cap in swing_caps:
        player_log = build_full_player_log_capped(raw, provisional_swing_cap=cap)
        b = brier_metrics(player_log, as_of)
        s = stability_metrics(player_log)
        cap_label = "None (current)" if cap is None else str(cap)
        print(
            f"{cap_label:>10} | "
            f"{b['brier'] if b['brier'] is not None else float('nan'):>7.4f} | "
            f"{b['log_loss'] if b['log_loss'] is not None else float('nan'):>8.4f} | "
            f"{s['players_evaluated']:>8} | "
            f"{s['players_with_2plus_80pt_swings']:>10} | "
            f"{s['pct_with_2plus_80pt_swings']:>10.1f}% | "
            f"{s['avg_max_swing_in_provisional_window']:>8.1f} | "
            f"{s['p90_max_swing_in_provisional_window']:>8.1f}"
        )


if __name__ == "__main__":
    main()
