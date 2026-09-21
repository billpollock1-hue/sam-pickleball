#!/bin/bash
set -e

# --- Overlap guard -----------------------------------------------------
# mkdir is atomic on POSIX filesystems, so this is safe against two cron
# invocations racing each other -- unlike flock, which isn't reliably
# available on macOS by default. Self-heals if a prior run crashed and
# left a stale lock behind (checks whether the recorded PID is still
# alive before deciding to steal the lock).
LOCKDIR="/tmp/sam_pickleball_run_all.lockdir"
LOCKPID="$LOCKDIR/pid"

acquire_lock() {
  mkdir "$LOCKDIR"
  echo $$ > "$LOCKPID"
  trap 'rm -rf "$LOCKDIR"' EXIT
}

if ! mkdir "$LOCKDIR" 2>/dev/null; then
  if [ -f "$LOCKPID" ] && kill -0 "$(cat "$LOCKPID")" 2>/dev/null; then
    echo "Another run_all.sh (PID $(cat "$LOCKPID")) is already running -- exiting."
    exit 0
  fi
  echo "Stale lock found -- removing and continuing."
  rm -rf "$LOCKDIR"
  acquire_lock
else
  echo $$ > "$LOCKPID"
  trap 'rm -rf "$LOCKDIR"' EXIT
fi
# -------------------------------------------------------------------------

# --- Stale git index.lock guard ------------------------------------------
# A crashed git process (this repo's own commit steps below, or an
# interrupted manual command) can leave .git/index.lock behind, which
# silently blocks EVERY future git operation -- confirmed real incident
# 2026-09-21: blocked 5.5+ hours of scheduled runs with no visible
# failure until someone noticed the published site showing stale data.
# Only removed if no other git process for this repo is actually running
# right now (checked via lsof on the lock file itself, not just a
# process-name match, since "git" alone is too broad a pgrep pattern).
GIT_LOCK=".git/index.lock"
if [ -f "$GIT_LOCK" ]; then
  if ! lsof "$GIT_LOCK" >/dev/null 2>&1; then
    echo "⚠ Found stale $GIT_LOCK with nothing holding it open -- removing."
    rm -f "$GIT_LOCK"
  else
    echo "⚠ Found $GIT_LOCK and something has it open -- leaving it alone and exiting."
    exit 1
  fi
fi
# -------------------------------------------------------------------------

echo ""
echo "=== Pickleball full update started ==="

MASTER_FILE="data/master_history_raw.csv"
LATEST_FILE="data/latest_scrape.csv"
STATE_FILE="data/.last_successful_rebuild_hash"
FINAL_OUTPUT="output/pickleball_model_latest.xlsx"
TEMP_OUTPUT="output/pickleball_model_latest_tmp.xlsx"
NO_SHOOTOUT_LOG="data/no_shootout_dates.csv"

echo ""
echo "0. Checking today's signup count (minimum 8 players required for a shootout)..."
(cd assignments && python3 check_no_shootout.py)

# Hash master history before any scrape/merge attempt. Steps 3-5c (summary
# workbook, rating engine, session viewer, storybook, leaderboard) are gated
# on this actually changing -- previously they ran unconditionally every
# time run_all.sh executed, even when the scrape found nothing and merge
# was skipped. The old guard ("single day AND fewer than 2 shootouts found")
# also missed the case where a stale multi-day window (e.g. spanning a
# weekend with no shootouts) legitimately found zero results but wasn't a
# literal single-day window, so it fell through and ran the full rebuild
# for no reason.
HASH_BEFORE=$(shasum -a 256 "$MASTER_FILE" | awk '{print $1}')

START_DATE=$(python3 - <<'PY'
import pandas as pd
from pathlib import Path

df = pd.read_csv(Path("data/master_history_raw.csv"))
dates = pd.to_datetime(df["posted"], errors="coerce").dropna()

if dates.empty:
    raise SystemExit("Could not find any valid posted dates in master history.")

latest_date = dates.max().normalize()
latest_date_d = latest_date.date()

partial_shootout_dates = set()
partial_path = Path("data/partial_shootout_dates.csv")
if partial_path.exists():
    psd = pd.read_csv(partial_path)
    partial_shootout_dates = set(pd.to_datetime(psd["date"], errors="coerce").dt.date.dropna())

# Only advance past the latest date if it's actually complete (both
# shootouts present, or explicitly logged as a genuine single-shootout
# day) -- otherwise re-scrape that same date to catch what's missing.
# Fixes a real bug (2026-09-14): always advancing to latest+1 regardless
# of completeness produced an inverted START_DATE > END_DATE window
# whenever today's own data was already partially present, which the
# scraper silently reported as "0 shootouts found" every single cycle.
if latest_date_d in partial_shootout_dates:
    latest_is_complete = True
else:
    day_mask = dates.dt.date == latest_date_d
    shootouts_present = {int(x) for x in df.loc[day_mask, "shootout"].dropna().unique()}
    latest_is_complete = {1, 2}.issubset(shootouts_present)

start = (latest_date + pd.Timedelta(days=1)) if latest_is_complete else latest_date
print(start.strftime("%m%d%y"))
PY
)

END_DATE=$(TZ=America/Phoenix date +"%m%d%y")

SHOULD_SKIP_SCRAPE=$(python3 - <<'PY'
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

df = pd.read_csv(Path("data/master_history_raw.csv"))
dates = pd.to_datetime(df["posted"], errors="coerce").dropna()
latest_date = dates.max().date()

partial_shootout_dates = set()
partial_path = Path("data/partial_shootout_dates.csv")
if partial_path.exists():
    psd = pd.read_csv(partial_path)
    partial_shootout_dates = set(pd.to_datetime(psd["date"], errors="coerce").dt.date.dropna())

def required_date_is_complete(d):
    """A date only counts as caught-up if both shootouts are present,
    unless it's explicitly logged as a genuine single-shootout day."""
    if d in partial_shootout_dates:
        return True
    day_mask = dates.dt.date == d
    shootouts_present = {int(x) for x in df.loc[day_mask, "shootout"].dropna().unique()}
    return {1, 2}.issubset(shootouts_present)

no_shootout_dates = set()
no_shootout_path = Path("data/no_shootout_dates.csv")
if no_shootout_path.exists():
    nsd = pd.read_csv(no_shootout_path)
    no_shootout_dates = set(pd.to_datetime(nsd["date"], errors="coerce").dt.date.dropna())

now_mtn  = datetime.now(ZoneInfo("America/Phoenix"))
today    = now_mtn.date()
CUTOFF   = time(7, 50)

if today.weekday() < 5:                        # weekday
    if now_mtn.time() >= CUTOFF:
        required_date = today                  # session data should be available by 8:15 AM MT
    else:
        required_date = today - timedelta(days=1)
        while required_date.weekday() >= 5 or required_date in no_shootout_dates:
            required_date -= timedelta(days=1)
else:                                          # weekend — use prior Friday
    required_date = today - timedelta(days=1)
    while required_date.weekday() >= 5 or required_date in no_shootout_dates:
        required_date -= timedelta(days=1)

# If today itself is a logged no-shootout date, there's nothing to wait for
# today either -- fall straight back to the prior real play date.
if today in no_shootout_dates:
    required_date = today - timedelta(days=1)
    while required_date.weekday() >= 5 or required_date in no_shootout_dates:
        required_date -= timedelta(days=1)

# A date only counts as "caught up" if it's strictly past the required
# date, or if it IS the required date AND that date's own data is
# actually complete (both shootouts present, or explicitly logged as a
# genuine single-shootout day). Fixes a real bug (2026-09-04): checking
# date presence alone let a partial day (only 1 of 2 shootouts scraped)
# permanently block every later cycle that day from re-checking, even
# though the missing shootout was sitting on Den's site all along.
if latest_date > required_date:
    print("YES")
elif latest_date == required_date and required_date_is_complete(required_date):
    print("YES")
else:
    print("NO")
PY
)

if [ "$SHOULD_SKIP_SCRAPE" = "YES" ]; then
  echo ""
  echo "1. Skipping scrape and merge."
  echo "Master history is already current through the most recent possible play date."
else
  echo ""
  echo "1. Scraping latest shootout data..."
  echo "Date window: $START_DATE through $END_DATE"
  echo "Update rule: scrape only when master history is behind the most recent possible play date."

  set +e
  SCRAPE_OUTPUT=$(node scraper/scrape.js --start "$START_DATE" --end "$END_DATE" --output "$LATEST_FILE" 2>&1)
  SCRAPE_EXIT=$?
  set -e
  echo "$SCRAPE_OUTPUT"
  if [ $SCRAPE_EXIT -ne 0 ]; then
    echo "⚠ Scraper exited with code $SCRAPE_EXIT — see output above for the actual error."
    exit $SCRAPE_EXIT
  fi

  SHOOTOUT_COUNT=$(echo "$SCRAPE_OUTPUT" | grep -o "Collected [0-9]* shootout" | grep -o "[0-9]*" || echo "0")

  # No automatic "give up and accept a partial day" logic. Recording a
  # date as no-shootout or single-shootout is always Bill's own manual
  # call (weather, etc.), made via the admin panel's Record a Date
  # feature -- never inferred automatically from a shootout count and
  # time of day. Removed 2026-09-14 after that automatic inference
  # never actually fired the day it mattered (see START_DATE fix above
  # for why) -- simpler and safer to just keep retrying every cycle
  # until either the data appears or Bill records the date manually.
  echo ""
  if [ "${SHOOTOUT_COUNT:-0}" -eq 0 ]; then
    echo "2. Skipping merge — no shootouts found in $START_DATE through $END_DATE."
    echo "   Nothing new to merge; master history stays as-is. Will retry on next"
    echo "   scheduled run. If today was cancelled or ran as a single shootout,"
    echo "   record it via the admin panel's Record a Date feature."
  elif [ "$START_DATE" = "$END_DATE" ] && [ "${SHOOTOUT_COUNT:-0}" -lt 2 ]; then
    echo "2. Skipping merge — only $SHOOTOUT_COUNT shootout(s) found for $START_DATE (need 2)."
    echo "   Results may not be fully posted yet. Will retry on next scheduled run."
    echo "   If today ran as a genuine single-shootout day, record it via the"
    echo "   admin panel's Record a Date feature."
  else
    echo "2. Cleaning/deduping master history..."
    python3 scraper/merge_csv.py
  fi
fi

HASH_AFTER=$(shasum -a 256 "$MASTER_FILE" | awk '{print $1}')

# Compare against the hash recorded the last time the rebuild block
# below actually COMPLETED successfully -- not just this run's own
# before/after snapshot (see STATE_FILE comment above for why).
LAST_SUCCESSFUL_HASH=""
if [ -f "$STATE_FILE" ]; then
  LAST_SUCCESSFUL_HASH=$(cat "$STATE_FILE")
fi

if [ "$HASH_AFTER" = "$LAST_SUCCESSFUL_HASH" ]; then
  DATA_CHANGED="NO"
else
  DATA_CHANGED="YES"
fi

if [ "$DATA_CHANGED" = "NO" ]; then
  echo ""
  echo "3-5c. Status quo — master history unchanged, skipping summary workbook,"
  echo "      rating engine, session viewer, storybook, and leaderboard rebuild."
else
  echo ""
  echo "3. Building 2026 summary workbook..."
  python3 engine/build_2026_summaries.py

  echo ""
  echo "4. Running rating engine..."
  rm -f "$TEMP_OUTPUT"

  python3 engine/pickleball_engine_v2.py \
    --input "$MASTER_FILE" \
    --output "$TEMP_OUTPUT"

  mv "$TEMP_OUTPUT" "$FINAL_OUTPUT"

  # Sync model inputs to the monitor runtime so the launchd agent can refresh
  # court assignments headlessly (it cannot read ~/Documents)
  PBM="$HOME/Library/Application Support/PBMonitor"
  if [ -d "$PBM" ]; then
    cp "$FINAL_OUTPUT" "$PBM/pickleball_model_latest.xlsx"
    cp "$MASTER_FILE" "$PBM/master_history_raw.csv"
    echo "Synced model workbook + history to monitor runtime."
  fi

  echo ""
  echo "5. Building session viewer..."
  python3 engine/build_session_viewer.py

  echo ""
  echo "5a2. Building player history..."
  python3 engine/build_player_history.py

  echo ""
  echo "5b. Building storybook..."
  python3 engine/build_storybook.py

  echo ""
  echo "5c. Building slim leaderboard..."
  python3 engine/build_leaderboard_html.py

  echo ""
  echo "5c3. Updating Format Change Tracker data..."
  python3 compute_format_tracker_data.py

  # Only record success now that every rebuild step above has
  # actually completed -- if any step above failed, the script
  # would have already exited (set -e) before reaching this line,
  # so STATE_FILE never gets the stale/incomplete hash.
  echo "$HASH_AFTER" > "$STATE_FILE"
fi

echo ""
echo "5c2. Building Ratings Change page..."
python3 engine/build_compare_ratings_html.py

echo ""
echo "5d. Refreshing court assignment snapshots..."
(cd assignments && python3 refresh_assignments.py)

echo ""
echo "5e. Building court assignments viewer..."
(cd assignments && python3 generate_assignments_viewer.py)

echo ""
echo "6. Updating docs/ for GitHub Pages..."
mkdir -p docs
cp output/session_viewer.html docs/
cp output/player_history.html docs/
cp output/leaderboard.html docs/
cp output/compare_ratings.html docs/
cp assignments/output/court_assignments_viewer.html docs/court_assignments.html
# storybook.html intentionally excluded from docs/ sync while still in development

echo ""
echo "7. Committing and pushing docs/ to GitHub Pages..."
if [ -n "$(git status --porcelain docs/)" ]; then
  git add docs/
  git commit -m "Auto-update GitHub Pages docs ($(TZ=America/Phoenix date '+%Y-%m-%d %H:%M') MST)"
  if git push origin main; then
    echo "Pushed docs/ updates to GitHub."
  else
    echo "⚠ git push failed — docs/ changes committed locally but NOT pushed. Manual attention needed."
  fi
else
  echo "No changes in docs/ — skipping commit."
fi

echo ""
echo "=== Done ==="
echo "Outputs are in: output/"
echo "Main ratings workbook: $FINAL_OUTPUT"
echo "Summary workbook: output/pickleball_2026_summary_report.xlsx"
echo "GitHub Pages files updated in: docs/"
