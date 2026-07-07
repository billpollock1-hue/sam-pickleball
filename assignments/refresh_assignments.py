#!/usr/bin/env python3
"""
Headless court-assignments refresh — no browser prompts, no manual steps.

Signup lists come from the signup monitor's state file (fresh within 15 min);
DEN step/percent ratings come from a headless fetch of the ratings page using
the saved session; model ratings come from the model workbook. Both assignment
methods are computed with den_assignments' own functions, then the JSON
snapshot and HTML viewer are regenerated.

Runs in two contexts:
  repo mode (default)     — invoked by Run Model.command after a model rebuild;
                            reads/writes under assignments/.
  runtime mode            — invoked by the launchd signup monitor with
                            PB_RUNTIME=~/Library/Application Support/PBMonitor
                            (launchd agents cannot access ~/Documents).

Usage:
  refresh_assignments.py [--dates 2026-07-06 ...]   # default: all open sheets
"""

import argparse
import json
import os
import sys
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from playwright.sync_api import sync_playwright

import den_assignments as da
import generate_assignments_viewer

STATE_FILE = Path.home() / "Library" / "Application Support" / "PBMonitor" / "signup_monitor_state.json"
MT = ZoneInfo("America/Denver")
SHEET_CLOSE = dtime(8, 0)  # monitor stops tracking a date after 8 AM MT that day


def sheet_is_open(date_str):
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    now = datetime.now(MT)
    if d > now.date():
        return True
    return d == now.date() and now.time() < SHEET_CLOSE


def load_signups(date_str):
    """Ordered signup list for a date from the monitor's state snapshots."""
    if not STATE_FILE.exists():
        print(f"State file not found: {STATE_FILE}")
        return None
    state = json.loads(STATE_FILE.read_text())
    snap = state.get("snapshots", {}).get(date_str)
    if not snap or not snap.get("players"):
        print(f"No snapshot players for {date_str}")
        return None
    return pd.DataFrame({
        "SignupOrder": range(1, len(snap["players"]) + 1),
        "Player": snap["players"],
    })


def fetch_den_ratings():
    """Headless fetch of the DEN ratings page using the saved session."""
    session = da.SESSION_FILE
    if not Path(session).exists():
        print(f"Session file missing: {session}")
        return pd.DataFrame()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=session)
        page = context.new_page()
        page.goto(da.RATINGS_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        text = page.locator("body").inner_text()
        # Persist any refreshed cookies for the next run
        context.storage_state(path=session)
        browser.close()
    return da.extract_ratings_from_text(text)


def ratings_through_date():
    if not da.MODEL_INPUT.exists():
        return None
    df = pd.read_csv(da.MODEL_INPUT, usecols=["posted"])
    dates = pd.to_datetime(df["posted"], errors="coerce").dropna()
    return dates.max().date() if not dates.empty else None


def refresh_date(date_str, den_ratings, player_ratings, ratings_through):
    signups = load_signups(date_str)
    if signups is None:
        return False
    if len(signups) < da.PLAYERS_PER_COURT:
        print(f"{date_str}: only {len(signups)} signups — skipping (need {da.PLAYERS_PER_COURT}).")
        return False

    if den_ratings.empty:
        assignments = pd.DataFrame()
        waitlist = pd.DataFrame()
    else:
        if den_ratings.empty:
        assignments = pd.DataFrame()
        waitlist = pd.DataFrame()
    else:
        assignments, waitlist = da.assign_courts(signups, den_ratings)

    rating_assignments = rating_waitlist = None
    if not player_ratings.empty:
        rating_assignments, rating_waitlist = da.assign_courts_by_rating(signups, player_ratings)

    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    da.save_assignments_snapshot(
        assignments, waitlist,
        play_date_file=date_str,
        play_date_display=da.format_display_date(d),
        total_signups=len(signups),
        rating_assignments=rating_assignments,
        rating_waitlist=rating_waitlist,
        ratings_through=ratings_through,
    )
    print(f"{date_str}: refreshed ({len(signups)} signups).")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", nargs="*", default=None,
                    help="Play dates (YYYY-MM-DD); default: all open sheets in monitor state")
    args = ap.parse_args()

    if args.dates:
        dates = [d for d in args.dates if sheet_is_open(d)]
    else:
        if not STATE_FILE.exists():
            print(f"State file not found: {STATE_FILE}")
            return 1
        state = json.loads(STATE_FILE.read_text())
        dates = sorted(d for d in state.get("snapshots", {}) if sheet_is_open(d))

    if not dates:
        print("No open signup sheets to refresh.")
        return 0

    den_ratings = fetch_den_ratings()
    if den_ratings.empty:
        print("⚠ DEN ratings fetch returned nothing — session may be expired.")
        print("  Proceeding with model ratings only. DEN Step/% columns will be empty.")
        print("  Run DEN Assignments manually to refresh the session.")

    player_ratings = da.load_player_ratings()
    ratings_through = ratings_through_date()

    any_ok = False
    for date_str in dates:
        try:
            if refresh_date(date_str, den_ratings, player_ratings, ratings_through):
                any_ok = True
        except Exception as e:
            print(f"{date_str}: refresh failed — {e}")

    if any_ok:
        # Viewer writes to Path("output") relative to cwd; anchor to our base dir
        os.chdir(Path(os.environ.get("PB_RUNTIME", Path(__file__).resolve().parent)))
        generate_assignments_viewer.generate_viewer()
        print("Viewer regenerated.")

    return 0 if any_ok else 1


if __name__ == "__main__":
    sys.exit(main())
