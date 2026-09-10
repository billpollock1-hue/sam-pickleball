"""
check_no_shootout.py

Runs as step 0 of run_all.sh, before the scrape-skip decision. Also invoked
every 15 minutes, all day, as part of the shootout-scraper launchd job.

DEN requires a minimum of 8 signed-up players to run a shootout. If today's
signup sheet has fewer than 8 players AT THE ACTUAL CUTOFF, there will be
no shootout today, and there's nothing to scrape.

This reads today's live player count directly from the signup monitor's own
state file (signup_monitor_state.json) rather than opening a separate browser
session. The monitor already polls DEN every 15 minutes and persists exactly
this information -- there's no reason to duplicate that work with a second,
slower, more fragile Playwright session (the original browser-based version
of this script hung for 30s on Vaadin's date-picker overlay). This version
has no browser dependency at all and should complete in well under a second.

CUTOFF-GATED WRITE (added after the shootout-scraper job moved to 15-minute
all-day polling): this script used to write a no-shootout record on ANY run
where the count was under 8 -- fine when it only ran 3x/day at 10:42 AM or
later, but with 15-minute polling starting well before dawn, an early-morning
run could see e.g. 7 signups (before people finished signing up) and lock in
"no shootout" hours before the real cutoff, even though the 8th player
signed up shortly after. Confirmed live 2026-07-23. Now only WRITES a
no-shootout record once the real cutoff (matching run_all.sh's own CUTOFF)
has actually passed.

SELF-CORRECTING: if today is currently marked no-shootout but a later check
finds the count has recovered to the real minimum (e.g. that same 8th
player, or a shootout gets manually launched anyway), the stale entry is
removed automatically -- a temporary early-morning dip should never
permanently block the rest of the day, since this script re-checks every
15 minutes regardless.

If under 8 at/after the cutoff, records today's date in
data/no_shootout_dates.csv so that:
  - run_all.sh's required_date walk-back treats today like a weekend (a date
    that never had -- and now provably won't have -- a shootout to scrape).
  - generate_assignments_viewer.py can warn accordingly instead of showing
    the misleading PRELIMINARY banner for this date.
  - launcher_poller.py skips attempting an automated launch for today.
"""

import json
from pathlib import Path
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

MIN_PLAYERS_FOR_SHOOTOUT = 8

# Matches Bill's confirmed 7:10 AM MST cutoff for the signup-count
# determination -- earlier than run_all.sh's own results-availability
# CUTOFF (8:15 AM), since this check only needs signups to be settled,
# not results to be posted.
CUTOFF = time(7, 10)

# Anchored to the script's own location, not the current working directory --
# run_all.sh invokes this via `(cd assignments && python3 check_no_shootout.py)`,
# and a cwd-relative "data/no_shootout_dates.csv" silently wrote to
# assignments/data/no_shootout_dates.csv instead of the repo-root data/ that
# run_all.sh's SHOULD_SKIP_SCRAPE block actually reads from. This resolves to
# the same repo-root data/ directory regardless of what cwd the script is
# launched from.
NO_SHOOTOUT_LOG = Path(__file__).resolve().parent.parent / "data" / "no_shootout_dates.csv"

# Deployed runtime copy of the signup monitor -- this is where the actual
# launchd job runs from and writes its state, per the known divergence
# between the git-tracked signup-monitor/ source and this live copy.
MONITOR_STATE_FILE = Path(
    "/Users/billpollock/Library/Application Support/PBMonitor/signup_monitor_state.json"
)


def now_mt():
    return datetime.now(ZoneInfo("America/Phoenix"))


def todays_date():
    return now_mt().date()


def get_todays_signup_count(today_str):
    if not MONITOR_STATE_FILE.exists():
        raise RuntimeError(f"Signup monitor state file not found: {MONITOR_STATE_FILE}")

    state = json.loads(MONITOR_STATE_FILE.read_text())
    snapshots = state.get("snapshots", {})

    if today_str not in snapshots:
        raise RuntimeError(
            f"No snapshot for {today_str} in signup monitor state yet -- "
            f"the monitor may not have polled today's sheet."
        )

    snap = snapshots[today_str]

    if snap.get("closed") and "players" not in snap:
        # Sheet marked closed before any players were ever recorded --
        # treat as zero signups rather than erroring.
        return 0, snap.get("last_checked")

    players = snap.get("players", [])
    return len(players), snap.get("last_checked")


def record_no_shootout(date_obj):
    NO_SHOOTOUT_LOG.parent.mkdir(parents=True, exist_ok=True)

    if NO_SHOOTOUT_LOG.exists():
        existing = pd.read_csv(NO_SHOOTOUT_LOG)
    else:
        existing = pd.DataFrame(columns=["date"])

    date_str = date_obj.strftime("%Y-%m-%d")
    if date_str in existing["date"].astype(str).values:
        print(f"{date_str} already recorded as a no-shootout date -- nothing to do.")
        return

    existing = pd.concat(
        [existing, pd.DataFrame([{"date": date_str}])], ignore_index=True
    )
    existing.to_csv(NO_SHOOTOUT_LOG, index=False)
    print(f"✓ Recorded {date_str} in {NO_SHOOTOUT_LOG} (fewer than "
          f"{MIN_PLAYERS_FOR_SHOOTOUT} players signed up, past cutoff).")


def remove_stale_no_shootout_entry(date_obj):
    """
    Self-correction: if today was previously (and, as of this run,
    incorrectly) marked no-shootout -- most likely an early-morning
    snapshot that has since recovered to the real minimum, or a shootout
    got manually launched anyway -- remove the stale entry rather than
    leaving today permanently blocked for the rest of the day.
    """
    if not NO_SHOOTOUT_LOG.exists():
        return
    existing = pd.read_csv(NO_SHOOTOUT_LOG)
    date_str = date_obj.strftime("%Y-%m-%d")
    if date_str not in existing["date"].astype(str).values:
        return
    existing = existing[existing["date"].astype(str) != date_str]
    existing.to_csv(NO_SHOOTOUT_LOG, index=False)
    print(f"✓ Removed stale no-shootout entry for {date_str} -- "
          f"signup count has recovered to the real minimum.")


def main():
    today = todays_date()
    today_str = today.strftime("%Y-%m-%d")
    now = now_mt()
    print(f"\n=== No-Shootout Check: {today.strftime('%A, %B %d, %Y')} MST ===\n")

    try:
        count, last_checked = get_todays_signup_count(today_str)
        checked_note = f" (as of monitor's last check: {last_checked})" if last_checked else ""
        print(f"Current signup count for {today_str}: {count}{checked_note}")

        if count >= MIN_PLAYERS_FOR_SHOOTOUT:
            remove_stale_no_shootout_entry(today)
            print(f"\nResult: shootout expected to run ({count} >= "
                  f"{MIN_PLAYERS_FOR_SHOOTOUT} minimum). No action needed.")
        elif now.time() < CUTOFF:
            print(f"\nResult: only {count} signed up so far, but it's before "
                  f"{CUTOFF.strftime('%-I:%M %p')} MST -- too early to judge. "
                  f"Not recording anything yet; will re-check on the next cycle.")
        else:
            record_no_shootout(today)
            print(f"\nResult: NO SHOOTOUT ({count} < {MIN_PLAYERS_FOR_SHOOTOUT} "
                  f"minimum, and the {CUTOFF.strftime('%-I:%M %p')} MST cutoff has passed).")

    except Exception as e:
        # Fail soft: if the state file is missing/stale/malformed, don't
        # block the rest of run_all.sh -- just proceed without recording
        # anything, exactly as if this check didn't exist.
        print(f"⚠ No-shootout check failed, proceeding without recording "
              f"anything for today: {e}")


if __name__ == "__main__":
    main()
