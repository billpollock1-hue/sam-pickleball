"""
Validates the recency-weighted Elo prototype against real game outcomes,
using the engine's own build_model_validation() -- the same tool that
checks whether the current rating model's predictions actually match what
happened on the courts (Brier score and log loss; lower is better for
both). This is what should decide the half-life, not intuition.

Compares three things head-to-head, all evaluated by the SAME validation
function so the comparison is apples-to-apples:
  1. BASELINE -- current full_player_log, pure cumulative Elo, no decay
     at all (this is what build_model_validation was originally written
     to check, and it's untouched by any of the window/union bugs).
  2. PROTOTYPE at several half-life settings -- recency-weighted, single
     continuous pass, no window, no union pool.

This does not touch the production no-history-drift/windowed system at
all -- that system is snapshot-based (tied to one as_of) and isn't
directly comparable through build_model_validation's continuous-log
design. This script is about picking a defensible half-life for a
REPLACEMENT mechanism, not re-litigating the union bug (already confirmed
separately).

Usage:
    cd "/Users/billpollock/Documents/SAM Pickleball/sam-pickleball/engine"
    python3 validate_recency_weighted_elo.py --input "../data/master_history_raw.csv"
"""
import argparse
from pathlib import Path
from collections import defaultdict

import pandas as pd

import pickleball_engine_v2 as eng


def build_recency_weighted_player_log(raw, as_of, half_life_days, floor=0.03):
    """
    Single continuous pass, chronological, no window and no union pool.
    Each game's K-factor is scaled by how far back in calendar time it
    sits from as_of. Includes all fields build_model_validation() needs
    (team_pre_rating, is_win, pf, pa) so it's a drop-in for that function.
    """
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
        if days_ago <= 0:
            recency = 1.0
        else:
            recency = max(floor, 0.5 ** (days_ago / half_life_days)) if include else 0.0

        if include:
            k_w1 = eng._provisional_k(player_game_count[w1] + 1) * recency
            k_w2 = eng._provisional_k(player_game_count[w2] + 1) * recency
            k_l1 = eng._provisional_k(player_game_count[l1] + 1) * recency
            k_l2 = eng._provisional_k(player_game_count[l2] + 1) * recency
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
            post = round(pre + delta, 2) if include else round(pre, 2)
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
    parser = argparse.ArgumentParser(description="Validate recency-weighted Elo against real outcomes.")
    parser.add_argument("--input", required=True, help="Path to master history CSV")
    parser.add_argument("--as-of", default=None, help="as-of date (defaults to latest date in the data)")
    args = parser.parse_args()

    raw = load_raw(Path(args.input))
    as_of = args.as_of or raw["posted_dt"].max().date()
    print(f"Validating as of {as_of}\n")

    print("=" * 90)
    print("BASELINE: current cumulative Elo (no decay, no window)")
    print("=" * 90)
    baseline_log = eng.build_full_player_log(raw)
    baseline_validation = eng.build_model_validation(baseline_log, as_of)
    summarize(baseline_validation, "Baseline (cumulative)")

    print("\n" + "=" * 90)
    print("PROTOTYPE: recency-weighted, no window, at several half-lives")
    print("=" * 90)
    results = []
    for half_life in [21, 30, 45, 60, 90, 120, 180, 270, 365, 730, 100000]:
        proto_log = build_recency_weighted_player_log(raw, as_of, half_life)
        proto_validation = eng.build_model_validation(proto_log, as_of)
        row = summarize(proto_validation, f"Half-life = {half_life} days")
        if row is not None:
            results.append({"half_life": half_life, "brier": row["Brier Score"], "log_loss": row["Log Loss"]})

    if results:
        best_brier = min(results, key=lambda r: r["brier"])
        best_logloss = min(results, key=lambda r: r["log_loss"])
        print("\n" + "=" * 90)
        print("BEST SETTINGS FOUND")
        print("=" * 90)
        print(f"Lowest Brier score:  half-life={best_brier['half_life']} days  (Brier={best_brier['brier']:.4f})")
        print(f"Lowest Log Loss:     half-life={best_logloss['half_life']} days  (Log Loss={best_logloss['log_loss']:.4f})")


if __name__ == "__main__":
    main()
