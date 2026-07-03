#!/bin/bash
set -e

echo ""
echo "=== Pickleball full update started ==="

MASTER_FILE="data/master_history_raw.csv"
LATEST_FILE="data/latest_scrape.csv"
FINAL_OUTPUT="output/pickleball_model_latest.xlsx"
TEMP_OUTPUT="output/pickleball_model_latest_tmp.xlsx"

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

now_mtn  = datetime.now(ZoneInfo("America/Denver"))
today    = now_mtn.date()
CUTOFF   = time(8, 15)

if today.weekday() < 5:                        # weekday
    if now_mtn.time() >= CUTOFF:
        required_date = today                  # session data should be available by 8:15 AM MT
    else:
        required_date = today - timedelta(days=1)
        while required_date.weekday() >= 5:    # walk back over any weekend
            required_date -= timedelta(days=1)
else:                                          # weekend — use prior Friday
    required_date = today - timedelta(days=1)
    while required_date.weekday() >= 5:
        required_date -= timedelta(days=1)

if latest_date > required_date:
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

  node scraper/scrape.js --start "$START_DATE" --end "$END_DATE" --output "$LATEST_FILE"

  echo ""
  echo "2. Cleaning/deduping master history..."
  python3 scraper/merge_csv.py
fi

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

echo ""
echo "5. Building session viewer..."
python3 engine/build_session_viewer.py

echo ""
echo "6. Updating docs/ for GitHub Pages..."
mkdir -p docs
cp output/session_viewer.html docs/
cp output/rating_history.html docs/
cp output/competitive_balance.html docs/
cp output/recent_trends.html docs/
cp output/consistency.html docs/

echo ""
echo "=== Done ==="
echo "Outputs are in: output/"
echo "Main ratings workbook: $FINAL_OUTPUT"
echo "Summary workbook: output/pickleball_2026_summary_report.xlsx"
echo "GitHub Pages files updated in: docs/"
