"""
Extended follow-up to parameter_sweep.py: pushes PROVISIONAL_K_GAMES and
PROVISIONAL_K_START further out to find where each actually plateaus
(neither had leveled off within the first sweep's range), then runs a
small joint grid over the two together, since they shape the same
underlying new-player calibration ramp and are the most likely pair in
this set to genuinely interact.

Holds the two settled findings from the first sweep fixed throughout:
  - K_FACTOR = 20 (confirmed near-optimal, no change)
  - margin_multiplier uncapped (confirmed monotonic improvement up to the
    mathematical maximum for an 11-0 game; capping was suppressing signal)

Usage:
    cd "/Users/billpollock/Documents/SAM Pickleball/sam-pickleball/engine"
    python3 parameter_sweep_extended.py --input "../data/master_history_raw.csv"
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
    # No cap -- confirmed by sweep D that the natural ceiling (log(12)=2.485
    # for an 11-0 game) is already the effective limit; an explicit cap
    # only ever suppresses signal, never adds anything.
    return math.log(abs(point_diff) + 1)


def run_validation(raw, as_of):
    log = eng.build_full_player_log(raw)
    validation = eng.build_model_validation(log, as_of)
    overall = validation[validation["Section"] == "Overall"]
    if overall.empty:
        return None, None
    row = overall.iloc[0]
    return row["Brier Score"], row["Log Loss"]


def sweep_provisional_games_extended(raw, as_of, values, fixed_start):
    print("\n" + "=" * 80)
    print(f"EXTENDED SWEEP B: PROVISIONAL_K_GAMES  (holding PROVISIONAL_K_START={fixed_start})")
    print("=" * 80)
    orig_start, orig_games = eng.PROVISIONAL_K_START, eng.PROVISIONAL_K_GAMES
    eng.PROVISIONAL_K_START = fixed_start
    results = []
    for v in values:
        eng.PROVISIONAL_K_GAMES = int(v)
        brier, logloss = run_validation(raw, as_of)
        print(f"  PROVISIONAL_K_GAMES={v:<6} Brier={brier:.4f}   Log Loss={logloss:.4f}")
        results.append((v, brier, logloss))
    eng.PROVISIONAL_K_START, eng.PROVISIONAL_K_GAMES = orig_start, orig_games
    return results


def sweep_provisional_start_extended(raw, as_of, values, fixed_games):
    print("\n" + "=" * 80)
    print(f"EXTENDED SWEEP C: PROVISIONAL_K_START  (holding PROVISIONAL_K_GAMES={fixed_games})")
    print("=" * 80)
    orig_start, orig_games = eng.PROVISIONAL_K_START, eng.PROVISIONAL_K_GAMES
    eng.PROVISIONAL_K_GAMES = fixed_games
    results = []
    for v in values:
        eng.PROVISIONAL_K_START = float(v)
        brier, logloss = run_validation(raw, as_of)
        print(f"  PROVISIONAL_K_START={v:<6} Brier={brier:.4f}   Log Loss={logloss:.4f}")
        results.append((v, brier, logloss))
    eng.PROVISIONAL_K_START, eng.PROVISIONAL_K_GAMES = orig_start, orig_games
    return results


def joint_grid(raw, as_of, games_values, start_values):
    print("\n" + "=" * 80)
    print("JOINT GRID: PROVISIONAL_K_GAMES x PROVISIONAL_K_START")
    print("=" * 80)
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
    print(f"Extended parameter sweep -- as of {as_of}")
    print("Fixed for all runs below: K_FACTOR=20, margin_multiplier UNCAPPED")

    orig_margin = eng.margin_multiplier
    eng.margin_multiplier = uncapped_margin_multiplier

    res_b = sweep_provisional_games_extended(raw, as_of, [60, 80, 120, 160, 200, 250, 300], fixed_start=40)
    res_c = sweep_provisional_start_extended(raw, as_of, [40, 50, 60, 70, 80, 100, 120], fixed_games=60)

    best_g = min(res_b, key=lambda r: r[1])[0]
    best_s = min(res_c, key=lambda r: r[1])[0]
    print(f"\nUnivariate winners so far: GAMES~{best_g}, START~{best_s} -- building joint grid around these")

    games_grid = sorted(set([max(60, best_g - 80), best_g, best_g + 80, best_g + 160]))
    start_grid = sorted(set([max(20, best_s - 20), best_s, best_s + 20, best_s + 40]))
    joint_results = joint_grid(raw, as_of, games_grid, start_grid)

    eng.margin_multiplier = orig_margin

    best = min(joint_results, key=lambda r: r[2])
    print("\n" + "=" * 80)
    print("JOINT GRID WINNER")
    print("=" * 80)
    print(f"  PROVISIONAL_K_GAMES={best[0]}  PROVISIONAL_K_START={best[1]}  "
          f"Brier={best[2]:.4f}  LogLoss={best[3]:.4f}")


if __name__ == "__main__":
    main()
