"""
Follow-up to parameter_sweep_extended.py: the joint grid's winner sat in
the corner of the tested range (low GAMES, low START relative to what was
tested), meaning the true optimum likely sits at LOWER values than we
checked -- possibly back near the current production defaults (60/40).
This extends the grid downward to find out, rather than assuming the
previous corner result was the true minimum.

Holds the same settled findings fixed: K_FACTOR=20, margin uncapped.

Usage:
    cd "/Users/billpollock/Documents/SAM Pickleball/sam-pickleball/engine"
    python3 parameter_sweep_downward.py --input "../data/master_history_raw.csv"
"""
import argparse
import math
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


def uncapped_margin_multiplier(point_diff):
    return math.log(abs(point_diff) + 1)


def run_validation(raw, as_of):
    log = eng.build_full_player_log(raw)
    validation = eng.build_model_validation(log, as_of)
    overall = validation[validation["Section"] == "Overall"]
    if overall.empty:
        return None, None
    row = overall.iloc[0]
    return row["Brier Score"], row["Log Loss"]


def joint_grid(raw, as_of, games_values, start_values):
    orig_start, orig_games = eng.PROVISIONAL_K_START, eng.PROVISIONAL_K_GAMES
    results = []
    header = "GAMES\\START".ljust(14) + "".join(f"{s:<10}" for s in start_values)
    print(header)
    for g in games_values:
        row_str = str(g).ljust(14)
        for s in start_values:
            eng.PROVISIONAL_K_GAMES = int(g)
            eng.PROVISIONAL_K_START = float(s)
            brier, logloss = run_validation(raw, as_of)
            results.append((g, s, brier, logloss))
            row_str += f"{brier:<10.4f}"
        print(row_str)
    eng.PROVISIONAL_K_START, eng.PROVISIONAL_K_GAMES = orig_start, orig_games
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--as-of", default=None)
    args = parser.parse_args()

    raw = load_raw(Path(args.input))
    as_of = args.as_of or raw["posted_dt"].max().date()
    print(f"Downward-extended joint grid -- as of {as_of}")
    print("Fixed: K_FACTOR=20, margin_multiplier UNCAPPED\n")

    orig_margin = eng.margin_multiplier
    eng.margin_multiplier = uncapped_margin_multiplier

    # Includes the current production defaults (60/40) explicitly, plus
    # lower values, plus a couple of the previous grid's lower corner
    # points as overlap to confirm continuity between the two grids.
    games_values = [60, 90, 130, 170, 220]
    start_values = [80, 100, 120, 150, 180]

    print("Brier Score grid:")
    results = joint_grid(raw, as_of, games_values, start_values)

    eng.margin_multiplier = orig_margin

    best = min(results, key=lambda r: r[2])
    current = [r for r in results if r[0] == 60 and r[1] == 40][0]

    print("\n" + "=" * 80)
    print("RESULT")
    print("=" * 80)
    print(f"  Current production (GAMES=60, START=40):  Brier={current[2]:.4f}  LogLoss={current[3]:.4f}")
    print(f"  Grid winner (GAMES={best[0]}, START={best[1]}):  Brier={best[2]:.4f}  LogLoss={best[3]:.4f}")
    print(f"  Difference: {round(current[2] - best[2], 4)} Brier")

    if best[0] in (games_values[0], games_values[-1]) or best[1] in (start_values[0], start_values[-1]):
        print("\n  NOTE: winner is still at the edge of the tested range -- may need to extend further.")
    else:
        print("\n  Winner sits inside the grid (not at an edge) -- this looks like a real interior optimum.")


if __name__ == "__main__":
    main()
