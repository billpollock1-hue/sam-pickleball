#!/usr/bin/env python3
"""
compute_format_tracker_data.py

Reads Player_Game_Log from the live model workbook and computes, per day:
  - average player_pre_rating across every player-appearance that day
  - a 7-day rolling average of that daily average
  - a player-appearance count

Writes launcher/format_tracker_data.json for format_tracker.html to consume.

Self-contained: no dependency on any other pipeline module. Safe to run
standalone at any time; always recomputes from the full history in the
workbook (single authoritative data source, no parallel calculation).
"""

import json
import sys
from datetime import date, datetime
from pathlib import Path

import openpyxl
import pandas as pd

# ---- Config -----------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent
WORKBOOK_PATH = REPO_ROOT / "output" / "pickleball_model_latest.xlsx"
OUTPUT_PATH = REPO_ROOT / "launcher" / "format_tracker_data.json"
SHEET_NAME = "Player_Game_Log"

# Format change effective date (shuffle-format change went live this date)
FORMAT_CHANGE_DATE = date(2026, 8, 24)

ROLLING_WINDOW_DAYS = 7


def load_game_log(workbook_path: Path) -> pd.DataFrame:
    if not workbook_path.exists():
        print(f"ERROR: workbook not found at {workbook_path}", file=sys.stderr)
        sys.exit(1)

    wb = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    if SHEET_NAME not in wb.sheetnames:
        print(f"ERROR: sheet '{SHEET_NAME}' not found in workbook", file=sys.stderr)
        sys.exit(1)

    ws = wb[SHEET_NAME]
    rows = ws.iter_rows(values_only=True)
    header = next(rows)
    df = pd.DataFrame(rows, columns=header)
    wb.close()
    return df


def compute_daily_series(df: pd.DataFrame) -> pd.DataFrame:
    # Only count games that actually feed the rating system.
    if "include_in_ratings" in df.columns:
        df = df[df["include_in_ratings"] == "Yes"].copy()

    df["posted_dt"] = pd.to_datetime(df["posted_dt"])
    df["play_date"] = df["posted_dt"].dt.date

    daily = (
        df.groupby("play_date")["player_pre_rating"]
        .agg(avg_rating="mean", count="count")
        .reset_index()
        .sort_values("play_date")
    )

    daily["rolling_avg"] = (
        daily["avg_rating"]
        .rolling(window=ROLLING_WINDOW_DAYS, min_periods=1)
        .mean()
    )

    return daily


def build_output(daily: pd.DataFrame) -> dict:
    pre = daily[daily["play_date"] < FORMAT_CHANGE_DATE]
    post = daily[daily["play_date"] >= FORMAT_CHANGE_DATE]

    last_pre_date = pre["play_date"].max() if not pre.empty else None
    first_post_date = post["play_date"].min() if not post.empty else None

    days = []
    for _, row in daily.iterrows():
        days.append({
            "date": row["play_date"].isoformat(),
            "avg_rating": round(float(row["avg_rating"]), 2),
            "rolling_avg": round(float(row["rolling_avg"]), 2),
            "count": int(row["count"]),
            "period": "before" if row["play_date"] < FORMAT_CHANGE_DATE else "after",
        })

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "format_change_date": FORMAT_CHANGE_DATE.isoformat(),
        "last_pre_change_date": last_pre_date.isoformat() if last_pre_date else None,
        "first_post_change_date": first_post_date.isoformat() if first_post_date else None,
        "rolling_window_days": ROLLING_WINDOW_DAYS,
        "days": days,
    }


def main():
    df = load_game_log(WORKBOOK_PATH)
    daily = compute_daily_series(df)
    output = build_output(daily)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {len(output['days'])} days to {OUTPUT_PATH}")
    print(f"Cutover: last pre-change day = {output['last_pre_change_date']}, "
          f"first post-change day = {output['first_post_change_date']}")


if __name__ == "__main__":
    main()
