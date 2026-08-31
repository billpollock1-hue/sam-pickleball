#!/usr/bin/env python3
"""
True before/after: imports the ORIGINAL engine (pre-investigation, with the
window/union contamination, the game_position_decay bug, capped margin,
0.85 compression, K=40/60 -- exactly as it shipped before this review) and
the FINAL corrected engine (no window, no decay bug, uncapped margin, 0.92
compression, K=40/60 restored) as two separate modules, and compares:

  1. build_model_validation() Brier/log loss -- both call this the same way
     the real workbook does (against full_player_log)
  2. Full leaderboard, old displayed rating (legacy's windowed
     build_last_n_leaderboard) vs new displayed rating
     (build_current_leaderboard), per player

No logic is reimplemented here -- every number comes from each engine's own
real functions, called directly.

Usage:
    python3 compare_legacy_vs_final.py --input ../data/master_history_raw.csv
    (run from a folder containing both legacy_engine.py and
     pickleball_engine_v2.py)
"""

import argparse
import importlib.util
import sys
from pathlib import Path

import pandas as pd


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_raw(eng, input_path):
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()

    here = Path(__file__).resolve().parent
    legacy = load_module(here / "legacy_engine.py", "legacy_engine")
    final = load_module(here / "pickleball_engine_v2.py", "final_engine")

    print("Loading and processing raw data for each engine (separately, using each engine's own loader)...")
    raw_legacy = load_raw(legacy, args.input)
    raw_final = load_raw(final, args.input)

    as_of = pd.Timestamp(raw_legacy["posted_dt"].max().date())

    # ---------- LEGACY: true original pipeline ----------
    print("Building legacy full_player_log (has the decay bug, old K, capped margin, 0.85 compression)...")
    legacy_full_log = legacy.build_full_player_log(raw_legacy)

    print("Running legacy's own no-history-drift windowed leaderboard construction...")
    legacy_recent_ids = legacy.collect_recent_match_ids_for_no_history_drift(legacy_full_log, as_of)
    legacy_raw_recent = raw_legacy.loc[[mid - 1 for mid in legacy_recent_ids]].copy().reset_index(drop=True)
    legacy_windowed_log = legacy.build_full_player_log(legacy_raw_recent)
    legacy_leaderboard = legacy.build_last_n_leaderboard(legacy_windowed_log, as_of)

    print("Running legacy's own model validation (against its own full_player_log, decay bug included)...")
    legacy_validation = legacy.build_model_validation(legacy_full_log, as_of)

    # ---------- FINAL: corrected pipeline ----------
    print("Building final full_player_log (no decay bug, K=40/60, uncapped margin, 0.92 compression)...")
    final_full_log = final.build_full_player_log(raw_final)

    print("Running final's own current leaderboard construction...")
    final_leaderboard = final.build_current_leaderboard(final_full_log, as_of)

    print("Running final's own model validation...")
    final_validation = final.build_model_validation(final_full_log, as_of)

    # ---------- Compare validation ----------
    print("\n" + "=" * 70)
    print("MODEL VALIDATION COMPARISON (Overall)")
    print("=" * 70)

    legacy_overall = legacy_validation[legacy_validation["Section"] == "Overall"]
    final_overall = final_validation[final_validation["Section"] == "Overall"]

    if not legacy_overall.empty and not final_overall.empty:
        lb, ll = float(legacy_overall["Brier Score"].iloc[0]), float(legacy_overall["Log Loss"].iloc[0])
        fb, fl = float(final_overall["Brier Score"].iloc[0]), float(final_overall["Log Loss"].iloc[0])
        print(f"{'':20} {'Brier':>10} {'LogLoss':>10}")
        print(f"{'LEGACY (original)':20} {lb:>10.4f} {ll:>10.4f}")
        print(f"{'FINAL (corrected)':20} {fb:>10.4f} {fl:>10.4f}")
        print(f"{'Difference':20} {fb-lb:>+10.4f} {fl-ll:>+10.4f}")
    else:
        print("Could not compute -- one of the validation dataframes was empty.")

    # ---------- Compare leaderboard ratings ----------
    print("\n" + "=" * 70)
    print("LEADERBOARD RATING COMPARISON (per player)")
    print("=" * 70)

    legacy_map = dict(zip(legacy_leaderboard["Player"], legacy_leaderboard["Player Rating"])) if not legacy_leaderboard.empty else {}
    final_map = dict(zip(final_leaderboard["Player"], final_leaderboard["Player Rating"])) if not final_leaderboard.empty else {}

    all_players = sorted(set(legacy_map) | set(final_map))
    rows = []
    for p in all_players:
        old = legacy_map.get(p)
        new = final_map.get(p)
        rows.append({
            "Player": p,
            "Legacy Rating": old,
            "Final Rating": new,
            "Difference": (new - old) if (old is not None and new is not None) else None,
        })

    comp = pd.DataFrame(rows)
    comp_both = comp.dropna(subset=["Difference"]).copy()
    comp_both = comp_both.sort_values("Difference", ascending=False)

    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 100)
    print(comp_both.to_string(index=False))

    only_legacy = comp[comp["Final Rating"].isna()]
    only_final = comp[comp["Legacy Rating"].isna()]
    if not only_legacy.empty:
        print(f"\nOn LEGACY leaderboard only ({len(only_legacy)}): {list(only_legacy['Player'])}")
    if not only_final.empty:
        print(f"\nOn FINAL leaderboard only ({len(only_final)}): {list(only_final['Player'])}")

    print(f"\nMean absolute difference: {comp_both['Difference'].abs().mean():.1f}")
    print(f"Median difference: {comp_both['Difference'].median():.1f}")
    print(f"Largest increase: {comp_both['Difference'].max():.1f} ({comp_both.iloc[0]['Player']})")
    print(f"Largest decrease: {comp_both['Difference'].min():.1f} ({comp_both.iloc[-1]['Player']})")


if __name__ == "__main__":
    main()
