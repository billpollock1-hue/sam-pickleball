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
    ratings = da.extract_ratings_from_text(text)

    # Rolling membership snapshot (added 2026-07-21): unconditional save on
    # every run of this file's 15-minute refresh cycle, unlike the older
    # DEBUG_MODE-gated dump in den_assignments.py itself. Presence of a
    # player's name in this file is the membership signal for the engine's
    # leaderboard exclusion filter.
    if not ratings.empty:
        ratings.to_csv(da.MEMBERSHIP_FILE, index=False)

    return ratings


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

    den_current = not den_ratings.empty
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
        den_current=den_current,
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
        sync_to_live_site()

    return 0 if any_ok else 1


def sync_to_live_site():
    """
    Copy the freshly-regenerated viewer into the real repo's docs/ folder
    and push it live, so signup changes detected by monitor_signups.py's
    15-minute cycle actually reach the live site -- not just the local
    output/ file.

    Without this, refresh_assignments.py only ever updated a LOCAL HTML
    file; nothing copied it into docs/ or pushed it to GitHub on this
    15-minute path. Only the separate, coarser run_all.sh schedule
    (8:15 AM / Noon / 5 PM) did that sync -- which is exactly why the
    court assignments page lagged behind real signup changes for hours
    at a time, even though this refresh was firing correctly underneath.

    Absolute path to the real repo -- NOT derived from cwd/PB_RUNTIME --
    since this script runs from two different locations (git-tracked
    source and the deployed PBMonitor runtime), same reasoning as the
    generate_signup_viewer.py DOCS_OUTPUT fix earlier.

    Runs unconditionally (no trial window) -- validated across a full
    production day (2026-07-17): confirmed catching a real signup change
    (Barnett/Barroso withdrawal) and pushing it to the live site within
    the same 15-minute cycle it was detected in.
    """
    import shutil
    import subprocess
    from datetime import datetime
    from zoneinfo import ZoneInfo

    repo_root = Path("/Users/billpollock/Documents/SAM Pickleball/sam-pickleball")
    local_viewer = Path("output") / "court_assignments_viewer.html"
    docs_target = repo_root / "docs" / "court_assignments.html"

    try:
        if not local_viewer.exists():
            print(f"  ⚠ sync_to_live_site: {local_viewer} not found -- skipping.")
            return

        docs_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(local_viewer, docs_target)

        status = subprocess.run(
            ["git", "status", "--porcelain", "docs/court_assignments.html"],
            cwd=str(repo_root), capture_output=True, text=True, timeout=30,
        )
        if not status.stdout.strip():
            print("  No change in docs/court_assignments.html — skipping git push.")
            return

        subprocess.run(["git", "add", "docs/court_assignments.html"],
                        cwd=str(repo_root), check=True, timeout=30)
        now = datetime.now(ZoneInfo("America/Phoenix")).strftime("%Y-%m-%d %H:%M")
        subprocess.run(
            ["git", "commit", "-m", f"Auto-refresh court assignments ({now} MST)"],
            cwd=str(repo_root), check=True, timeout=30,
        )
        push = subprocess.run(["git", "push", "origin", "main"],
                               cwd=str(repo_root), capture_output=True, text=True, timeout=60)
        if push.returncode == 0:
            print("  ✓ Pushed updated court assignments to live site.")
        else:
            print(f"  ⚠ git push failed (committed locally, not pushed): "
                  f"{push.stderr[-300:]}")
    except Exception as e:
        print(f"  ⚠ sync_to_live_site failed: {e}")


if __name__ == "__main__":
    sys.exit(main())
