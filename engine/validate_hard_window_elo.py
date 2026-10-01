"""
Validates a literal HARD-WINDOWED Elo against real game outcomes, using the
engine's own build_model_validation() -- the same tool validate_recency_
weighted_elo.py uses. That script tested smooth exponential recency decay
(old games never fully drop out, just fade). This tests the other thing
people actually propose: a hard cutoff -- games older than N months don't
count at all, full stop, same as starting a player over at Base Elo for
any game outside the window.

Mechanism: single continuous pass, chronological, exactly like the
recency-weighted script, except a game's K-factor is either the normal
provisional K (if within window_days of the fixed as-of date) or exactly
zero (if older) -- no partial credit, no floor. A player's rating is
therefore BASE_ELO plus the sum of only their in-window games' deltas,
which is the most literal, charitable reading of "just use the last N
months" -- nothing clever, no attempt to carry forward pre-window skill.

Usage:
    cd "/Users/billpollock/Documents/SAM Pickleball/sam-pickleball/engine"
    python3 validate_hard_window_elo.py --input "../data/master_history_raw.csv"
"""
import argparse
from pathlib import Path
from collections import defaultdict

import pandas as pd

import pickleball_engine_v2 as eng


def build_hard_window_player_log(raw, as_of, window_days):
    as_of_cutoff = pd.Timestamp(as_of).normalize() + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    scoped = raw[raw["posted_dt"] <= as_of_cutoff].copy().reset_index(drop=True)

    ratings = defaultdict(lambda: eng.BASE_ELO)
    player_game_count = defaultdict(int)
    player_rows = []

    for match_id, (_, r) in enumerate(scoped.iterrows(), start=1):
        w1, w2 = eng.split_team(r["winning_team"])
        l1, l2 = eng.split_team(r["losing_team"])
        sw, sl = int(r["winning_score"]), int(r["losing_score"])
        include = bool(r["include_in_ratings"])

        snap = {p: ratings[p] for p in [w1, w2, l1, l2]}
        team_win_pre = (snap[w1] + snap[w2]) / 2
        team_lose_pre = (snap[l1] + snap[l2]) / 2
        exp_win = eng.expected(team_win_pre, team_lose_pre)
        exp_lose = 1 - exp_win
        mult = eng.margin_multiplier(sw - sl)

        days_ago = (as_of_cutoff.normalize() - pd.Timestamp(r["posted_dt"]).normalize()).days
        in_window = days_ago <= window_days

        if include and in_window:
            k_w1 = eng._provisional_k(player_game_count[w1] + 1)
            k_w2 = eng._provisional_k(player_game_count[w2] + 1)
            k_l1 = eng._provisional_k(player_game_count[l1] + 1)
            k_l2 = eng._provisional_k(player_game_count[l2] + 1)
        else:
            k_w1 = k_w2 = k_l1 = k_l2 = 0.0

        d_w1 = round(k_w1 * (1 - exp_win) * mult, 2)
        d_w2 = round(k_w2 * (1 - exp_win) * mult, 2)
        d_l1 = round(k_l1 * (0 - exp_lose) * mult, 2)
        d_l2 = round(k_l2 * (0 - exp_lose) * mult, 2)

        rows_for_game = [
            (w1, 1, sw, sl, team_win_pre, d_w1),
            (w2, 1, sw, sl, team_win_pre, d_w2),
            (l1, 0, sl, sw, team_lose_pre, d_l1),
            (l2, 0, sl, sw, team_lose_pre, d_l2),
        ]

        for player, is_win, pf, pa, team_pre, delta in rows_for_game:
            pre = snap[player]
            post = round(pre + delta, 2) if (include and in_window) else round(pre, 2)
            player_rows.append({
                "match_id": match_id,
                "posted_dt": r["posted_dt"],
                "posted": r["posted_dt"].date(),
                "player": player,
                "is_win": is_win,
                "pf": pf,
                "pa": pa,
                "team_pre_rating": round(team_pre, 2),
                "player_pre_rating": round(pre, 2),
                "player_post_rating": post,
                "include_in_ratings": "Yes" if (include and in_window) else "No",
            })

        if include and in_window:
            ratings[w1] = round(snap[w1] + d_w1, 2)
            ratings[w2] = round(snap[w2] + d_w2, 2)
            ratings[l1] = round(snap[l1] + d_l1, 2)
            ratings[l2] = round(snap[l2] + d_l2, 2)
            player_game_count[w1] += 1
            player_game_count[w2] += 1
            player_game_count[l1] += 1
            player_game_count[l2] += 1

    return pd.DataFrame(player_rows)


def summarize(validation_df, label):
    overall = validation_df[validation_df["Section"] == "Overall"]
    if overall.empty:
        print(f"{label:<30} -- no qualifying games")
        return None
    row = overall.iloc[0]
    print(f"{label:<30} Games={int(row['Games']):<6} "
          f"Brier={row['Brier Score']:.4f}   Log Loss={row['Log Loss']:.4f}   "
          f"(lower is better for both)")
    return row


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
    parser = argparse.ArgumentParser(description="Validate hard-windowed Elo against real outcomes.")
    parser.add_argument("--input", required=True, help="Path to master history CSV")
    parser.add_argument("--as-of", default=None, help="as-of date (defaults to latest date in the data)")
    args = parser.parse_args()

    raw = load_raw(Path(args.input))
    as_of = args.as_of or raw["posted_dt"].max().date()
    print(f"Validating as of {as_of}\n")

    print("=" * 90)
    print("BASELINE: current cumulative Elo (full history, no window)")
    print("=" * 90)
    baseline_log = eng.build_full_player_log(raw)
    baseline_validation = eng.build_model_validation(baseline_log, as_of)
    summarize(baseline_validation, "Baseline (full history)")

    print("\n" + "=" * 90)
    print("HARD WINDOW: only games within the trailing N months count at all")
    print("=" * 90)
    for months in [6, 9, 12, 18, 24, 36, 48]:
        window_days = round(months * 30.44)
        win_log = build_hard_window_player_log(raw, as_of, window_days)
        win_validation = eng.build_model_validation(win_log, as_of)
        summarize(win_validation, f"{months} months ({window_days}d)")


if __name__ == "__main__":
    main()
