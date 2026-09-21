"""
Step 2: full parameter sweep for K-factor, provisional-K shape, and the
margin-multiplier cap -- tested against real 2026 outcomes via the engine's
own build_model_validation(), on the cumulative (no-window) rating basis
already confirmed best.

This is a univariate sweep (one parameter varied at a time, others held at
current production defaults) rather than a full combinatorial grid -- a
first pass to see which parameters matter and in which direction, before
deciding whether a joint sweep is worth the extra runtime.

Each run monkey-patches the relevant constant(s)/function on the eng module,
rebuilds full_player_log from scratch, runs validation, then restores the
original values. Nothing is written back to the engine file itself.

Usage:
    cd "/Users/billpollock/Documents/SAM Pickleball/sam-pickleball/engine"
    python3 parameter_sweep.py --input "../data/master_history_raw.csv"
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


def run_validation(raw, as_of):
    """Rebuilds the log with whatever eng.* constants/functions are
    currently patched, and returns the Overall Brier/Log Loss row."""
    log = eng.build_full_player_log(raw)
    validation = eng.build_model_validation(log, as_of)
    overall = validation[validation["Section"] == "Overall"]
    if overall.empty:
        return None, None
    row = overall.iloc[0]
    return row["Brier Score"], row["Log Loss"]


def make_margin_multiplier(cap):
    def _margin_multiplier(point_diff):
        return min(math.log(abs(point_diff) + 1), cap)
    return _margin_multiplier


def sweep_k_factor(raw, as_of, values):
    print("\n" + "=" * 80)
    print(f"SWEEP A: K_FACTOR (steady-state K)  [current = {eng.K_FACTOR}]")
    print("(holding PROVISIONAL_K_START=40, PROVISIONAL_K_GAMES=60)")
    print("=" * 80)
    orig = eng.K_FACTOR
    results = []
    for v in values:
        eng.K_FACTOR = float(v)
        brier, logloss = run_validation(raw, as_of)
        marker = "  <-- current" if v == orig else ""
        print(f"  K_FACTOR={v:<6} Brier={brier:.4f}   Log Loss={logloss:.4f}{marker}")
        results.append((v, brier, logloss))
    eng.K_FACTOR = orig
    return results


def sweep_provisional_games(raw, as_of, values):
    print("\n" + "=" * 80)
    print(f"SWEEP B: PROVISIONAL_K_GAMES (length of new-player ramp)  [current = {eng.PROVISIONAL_K_GAMES}]")
    print("(holding K_FACTOR=20, PROVISIONAL_K_START=40)")
    print("=" * 80)
    orig = eng.PROVISIONAL_K_GAMES
    results = []
    for v in values:
        eng.PROVISIONAL_K_GAMES = int(v)
        brier, logloss = run_validation(raw, as_of)
        marker = "  <-- current" if v == orig else ""
        print(f"  PROVISIONAL_K_GAMES={v:<6} Brier={brier:.4f}   Log Loss={logloss:.4f}{marker}")
        results.append((v, brier, logloss))
    eng.PROVISIONAL_K_GAMES = orig
    return results


def sweep_provisional_start(raw, as_of, values):
    print("\n" + "=" * 80)
    print(f"SWEEP C: PROVISIONAL_K_START (initial K for brand-new players)  [current = {eng.PROVISIONAL_K_START}]")
    print("(holding K_FACTOR=20, PROVISIONAL_K_GAMES=60)")
    print("=" * 80)
    orig = eng.PROVISIONAL_K_START
    results = []
    for v in values:
        eng.PROVISIONAL_K_START = float(v)
        brier, logloss = run_validation(raw, as_of)
        marker = "  <-- current" if v == orig else ""
        print(f"  PROVISIONAL_K_START={v:<6} Brier={brier:.4f}   Log Loss={logloss:.4f}{marker}")
        results.append((v, brier, logloss))
    eng.PROVISIONAL_K_START = orig
    return results


def sweep_margin_cap(raw, as_of, values):
    print("\n" + "=" * 80)
    print("SWEEP D: margin_multiplier cap  [current = 2.0]")
    print("(pickleball games to 11 -> max uncapped value is log(12)=2.485)")
    print("=" * 80)
    orig = eng.margin_multiplier
    results = []
    for v in values:
        eng.margin_multiplier = make_margin_multiplier(v)
        brier, logloss = run_validation(raw, as_of)
        marker = "  <-- current" if abs(v - 2.0) < 0.001 else ""
        print(f"  cap={v:<6} Brier={brier:.4f}   Log Loss={logloss:.4f}{marker}")
        results.append((v, brier, logloss))
    eng.margin_multiplier = orig
    return results


def report_best(results, label, param_name):
    best_brier = min(results, key=lambda r: r[1])
    best_logloss = min(results, key=lambda r: r[2])
    print(f"  Best for {label} by Brier:    {param_name}={best_brier[0]}  (Brier={best_brier[1]:.4f})")
    print(f"  Best for {label} by LogLoss:  {param_name}={best_logloss[0]}  (LogLoss={best_logloss[2]:.4f})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--as-of", default=None)
    args = parser.parse_args()

    raw = load_raw(Path(args.input))
    as_of = args.as_of or raw["posted_dt"].max().date()
    print(f"Parameter sweep -- as of {as_of}, cumulative rating basis, univariate (one at a time)")

    res_k = sweep_k_factor(raw, as_of, [10, 15, 20, 25, 30, 35, 40])
    res_pgames = sweep_provisional_games(raw, as_of, [20, 40, 60, 80, 120])
    res_pstart = sweep_provisional_start(raw, as_of, [20, 25, 30, 35, 40, 50, 60])
    res_margin = sweep_margin_cap(raw, as_of, [1.0, 1.5, 2.0, 2.485, 3.0])

    print("\n" + "=" * 80)
    print("SUMMARY -- best setting found per parameter (holding others at current default)")
    print("=" * 80)
    report_best(res_k, "K_FACTOR", "K_FACTOR")
    report_best(res_pgames, "PROVISIONAL_K_GAMES", "PROVISIONAL_K_GAMES")
    report_best(res_pstart, "PROVISIONAL_K_START", "PROVISIONAL_K_START")
    report_best(res_margin, "margin cap", "cap")
    print("\nNote: this is a univariate sweep -- if two parameters interact,")
    print("the true joint optimum could differ from the best univariate settings.")
    print("Worth a joint sweep only if these results suggest meaningfully different values.")


if __name__ == "__main__":
    main()
