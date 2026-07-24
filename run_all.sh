#!/bin/bash
set -e

echo ""
echo "=== Pickleball full update started ==="

MASTER_FILE="data/master_history_raw.csv"
LATEST_FILE="data/latest_scrape.csv"
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

next_day = dates.max().normalize() + pd.Timedelta(days=1)
print(next_day.strftime("%m%d%y"))
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

no_shootout_dates = set()
no_shootout_path = Path("data/no_shootout_dates.csv")
if no_shootout_path.exists():
    nsd = pd.read_csv(no_shootout_path)
    no_shootout_dates = set(pd.to_datetime(nsd["date"], errors="coerce").dt.date.dropna())

now_mtn  = datetime.now(ZoneInfo("America/Phoenix"))
today    = now_mtn.date()
CUTOFF   = time(8, 15)

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

# Use >= rather than > so that master history being caught up EXACTLY
# through the required date (not just ahead of it) also triggers a skip.
# Without this, latest_date == required_date fell through to "NO", which
# proceeded to scrape with an inverted START_DATE > END_DATE window.
if latest_date >= required_date:
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

  # Past-noon give-up check -- only meaningful for a single-day window
  # checking today itself (not a multi-day catch-up scrape). Bill's own
  # data: a day with at least one real shootout posts it by 7:15 AM
  # 99.99% of the time; the second posts by 7:50 AM 95% of the time, by
  # 8:15 AM 98.9% of the time, and a rare missed-score hunt "almost always"
  # resolves by noon. So: keep retrying (the existing "will retry on next
  # scheduled run" path below) until noon; at/after noon, stop waiting and
  # finalize with whatever count actually exists -- 1 shootout means a
  # genuine partial day (e.g. weather cut the second one short), 0 means
  # a full cancellation after enough players had signed up (the same
  # after-the-fact-weather-cancellation case handled manually for
  # 2026-07-17, now automatic).
  PAST_NOON="NO"
  if [ "$START_DATE" = "$END_DATE" ]; then
    NOW_HOUR_MST=$(TZ=America/Phoenix date +%H)
    if [ "$NOW_HOUR_MST" -ge 12 ]; then
      PAST_NOON="YES"
    fi
  fi

  echo ""
  if [ "${SHOOTOUT_COUNT:-0}" -eq 0 ] && [ "$PAST_NOON" = "NO" ]; then
    echo "2. Skipping merge — no shootouts found in $START_DATE through $END_DATE."
    echo "   Nothing new to merge; master history stays as-is."
  elif [ "$START_DATE" = "$END_DATE" ] && [ "${SHOOTOUT_COUNT:-0}" -lt 2 ] && [ "$PAST_NOON" = "NO" ]; then
    echo "2. Skipping merge — only $SHOOTOUT_COUNT shootout(s) found for $START_DATE (need 2)."
    echo "   Results may not be fully posted yet. Will retry on next scheduled run."
  elif [ "$START_DATE" = "$END_DATE" ] && [ "${SHOOTOUT_COUNT:-0}" -eq 0 ] && [ "$PAST_NOON" = "YES" ]; then
    echo "2. Past noon with zero shootouts found for $START_DATE — treating as a full"
    echo "   cancellation after signups (e.g. weather) rather than continuing to retry."
    python3 - <<PY
import pandas as pd
from pathlib import Path
import datetime as dt
log = Path("data/no_shootout_dates.csv")
# START_DATE is MMDDYY (scrape.js's own format) -- convert to the
# YYYY-MM-DD format the rest of the pipeline actually uses.
date_str = dt.datetime.strptime("$START_DATE", "%m%d%y").strftime("%Y-%m-%d")
existing = pd.read_csv(log) if log.exists() else pd.DataFrame(columns=["date"])
if date_str not in existing["date"].astype(str).values:
    existing = pd.concat([existing, pd.DataFrame([{"date": date_str}])], ignore_index=True)
    existing.to_csv(log, index=False)
    print(f"  Recorded {date_str} in {log}.")
else:
    print(f"  {date_str} already recorded in {log}.")
PY
  elif [ "$START_DATE" = "$END_DATE" ] && [ "${SHOOTOUT_COUNT:-0}" -eq 1 ] && [ "$PAST_NOON" = "YES" ]; then
    echo "2. Past noon with only 1 of 2 shootouts found for $START_DATE — accepting the"
    echo "   partial day and merging what exists rather than continuing to retry."
    python3 - <<PY
import pandas as pd
from pathlib import Path
import datetime as dt
log = Path("data/partial_shootout_dates.csv")
date_str = dt.datetime.strptime("$START_DATE", "%m%d%y").strftime("%Y-%m-%d")
existing = pd.read_csv(log) if log.exists() else pd.DataFrame(columns=["date"])
if date_str not in existing["date"].astype(str).values:
    existing = pd.concat([existing, pd.DataFrame([{"date": date_str}])], ignore_index=True)
    existing.to_csv(log, index=False)
    print(f"  Recorded {date_str} in {log}.")
else:
    print(f"  {date_str} already recorded in {log}.")
PY
    echo "2b. Cleaning/deduping master history..."
    python3 scraper/merge_csv.py
  else
    echo "2. Cleaning/deduping master history..."
    python3 scraper/merge_csv.py
  fi
fi

HASH_AFTER=$(shasum -a 256 "$MASTER_FILE" | awk '{print $1}')

if [ "$HASH_BEFORE" = "$HASH_AFTER" ]; then
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
    --output "$TEMP_OUTPUT" \
    --with-history

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
  echo "5b. Building storybook..."
  python3 engine/build_storybook.py

  echo ""
  echo "5c. Building slim leaderboard..."
  python3 engine/build_leaderboard_html.py
fi

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
cp output/rating_history.html docs/
cp output/competitive_balance.html docs/
cp output/recent_trends.html docs/
cp output/consistency.html docs/
cp output/leaderboard.html docs/
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
