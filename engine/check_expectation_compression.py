"""
Step 1 of the parameter review: pull the expectation-compression sensitivity
table that build_model_validation() already computes -- data we already
generated during the decay validation, just never looked at.

EXPECTATION_COMPRESSION = 0.85 is currently hardcoded in the engine. This
table tests factors from 1.00 (no compression) down to 0.70 against real
2026 outcomes, using the SAME rating basis we just confirmed is best: plain
cumulative Elo, no window, no decay. Whichever factor produces the lowest
Brier score / log loss is the one the data actually supports.

Usage:
    cd "/Users/billpollock/Documents/SAM Pickleball/sam-pickleball/engine"
    python3 check_expectation_compression.py --input "../data/master_history_raw.csv"
"""
import argparse
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--as-of", default=None)
    args = parser.parse_args()

    raw = load_raw(Path(args.input))
    as_of = args.as_of or raw["posted_dt"].max().date()

    full_player_log = eng.build_full_player_log(raw)
    validation = eng.build_model_validation(full_player_log, as_of)

    print(f"Expectation-compression sensitivity (as of {as_of}, cumulative rating basis)")
    print(f"Current hardcoded EXPECTATION_COMPRESSION = {eng.EXPECTATION_COMPRESSION}")
    print("=" * 80)

    comp = validation[validation["Section"] == "Expectation compression test"].copy()
    comp["Bucket"] = comp["Bucket"].astype(float)
    comp = comp.sort_values("Bucket", ascending=False)

    print(f"{'Factor':<10}{'Games':<8}{'Brier Score':<15}{'Log Loss':<15}")
    print("-" * 80)
    for _, row in comp.iterrows():
        marker = "  <-- current hardcoded value" if abs(row["Bucket"] - eng.EXPECTATION_COMPRESSION) < 0.001 else ""
        print(f"{row['Bucket']:<10}{int(row['Games']):<8}{row['Brier Score']:<15.4f}{row['Log Loss']:<15.4f}{marker}")

    best_brier = comp.loc[comp["Brier Score"].idxmin()]
    best_logloss = comp.loc[comp["Log Loss"].idxmin()]
    print("\n" + "=" * 80)
    print(f"Lowest Brier score:  factor={best_brier['Bucket']}  (Brier={best_brier['Brier Score']:.4f})")
    print(f"Lowest Log Loss:     factor={best_logloss['Bucket']}  (Log Loss={best_logloss['Log Loss']:.4f})")


if __name__ == "__main__":
    main()
