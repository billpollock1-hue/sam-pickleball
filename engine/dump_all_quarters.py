#!/usr/bin/env python3
"""
The storybook's "Growing Competitiveness Problem" chapter only ever shows
4 hardcoded quarters (2022 Q1, 2023 Q1, 2024 Q1, 2025 Q2) plus whatever the
latest quarter is. This dumps EVERY quarter so we can see the actual shape
of the trend -- not just the two endpoints the "1.7x" headline is computed
from.

Usage:
    python3 dump_all_quarters.py --input ../data/master_history_raw.csv
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pickleball_engine_v2 as engine  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()

    raw = pd.read_csv(args.input)
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

    full_player_log = engine.build_full_player_log(raw)
    cb = engine.build_competitive_balance_by_quarter(full_player_log)

    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 120)
    cb_display = cb.copy()
    cb_display["Avg Gap"] = cb_display["Avg Gap"].round(0).astype(int)
    cb_display["Median Gap"] = cb_display["Median Gap"].round(0).astype(int)
    cb_display["90th %ile Gap"] = cb_display["90th %ile Gap"].round(0).astype(int)
    cb_display["% Under 200"] = (cb_display["% Under 200"] * 100).round(0).astype(int)
    cb_display["% Decided by <=3"] = (cb_display["% Decided by <=3"] * 100).round(0).astype(int)
    cb_display["% Decided by 9+"] = (cb_display["% Decided by 9+"] * 100).round(0).astype(int)

    print(cb_display[["Quarter", "Games", "Avg Gap", "Median Gap", "90th %ile Gap",
                       "% Under 200", "% Decided by <=3", "% Decided by 9+"]].to_string(index=False))

    # Quarter-over-quarter change, to see where the actual movement happens
    print("\n--- Quarter-over-quarter change in Avg Gap ---")
    prev = None
    for _, r in cb.iterrows():
        if prev is not None:
            change = r["Avg Gap"] - prev
            pct = (change / prev * 100) if prev else 0
            print(f"{r['Quarter']}: {r['Avg Gap']:.0f}  ({change:+.0f}, {pct:+.1f}%)")
        else:
            print(f"{r['Quarter']}: {r['Avg Gap']:.0f}  (baseline)")
        prev = r["Avg Gap"]


if __name__ == "__main__":
    main()
