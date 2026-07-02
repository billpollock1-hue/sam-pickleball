# Pickleball Model

Elo-based player rating system for the Anthem SAM 6 AM Shootout. Scrapes match results from Pickleball Den, builds ratings, and produces Excel workbooks.

---

## Directory Structure

```
PickleballModel/
├── scrape.js                        # Playwright scraper — pulls shootout scores from Pickleball Den
├── merge_csv.py                     # Deduplicates new scrapes into master_history_raw.csv
├── pickleball_engine_v2.py          # Core Elo rating engine — main model
├── build_2026_summaries.py          # Win/loss stats workbook (no Elo)
├── run_all.sh                       # Runs scrape → merge → model in sequence
├── den_session.json                 # Saved Pickleball Den login session
├── den_credentials.json             # Login credentials for auto-login
├── den_config.json                  # Saved Club Play List URL
├── data/
│   ├── master_history_raw.csv       # Full game history (Jan 2022–present)
│   ├── latest_scrape.csv            # Output of the most recent scrape run
│   └── backups/                     # Point-in-time backups before data corrections
├── output/
│   ├── pickleball_model_latest.xlsx # Main model output — ratings, leaderboard, analysis
│   └── pickleball_2026_summary_report.xlsx  # Win/loss summary workbook
└── tools/
    ├── add_workbook_glossaries.py   # Utility: adds glossary tabs to workbooks
    └── analyze_patterns.py          # Utility: additional pattern analysis
```

---

## Normal Workflow

```bash
cd ~/Documents/"SAM Pickleball/PickleballModel"
./run_all.sh
```

Or run steps individually:

```bash
node scrape.js --start MMDDYY --end MMDDYY   # scrape new scores
python3 merge_csv.py                           # merge into master history
python3 pickleball_engine_v2.py               # build ratings
```

---

## Scraper (`scrape.js`)

Playwright-based scraper that navigates the Pickleball Den Club Play List and extracts game scores.

- Requires Node.js and Playwright (`npm install` in this folder if needed)
- Uses `den_session.json` for saved login; falls back to `den_credentials.json` for auto-login
- Takes `--start` and `--end` date arguments (format: `MMDDYY`)
- Output goes to `data/latest_scrape.csv`

---

## Rating Engine (`pickleball_engine_v2.py`)

Elo-based model with the following adjustments:

- **K-factor:** 24
- **Window:** Last 60 games per player
- **Freshness decay:** Ratings fade slightly after 90 days of inactivity
- **Credibility adjustment:** New players' ratings are dampened until they have enough games

Output: `output/pickleball_model_latest.xlsx`

### Workbook Tabs

Leaderboard, Model Description, Key Findings, Model Validation, Expected Margin Calibration, Team Balance Analysis, Extreme Partner Spread, Extreme Spread Detail, Extreme Spread Summary, Competitive Balance, Player Pool, Pool vs Balance, Credibility Sensitivity, Performance vs Expectation, AB Court Planning, Session Effects, Recent Trends, Consistency, Game Consistency, Recent Best Worst Day, Rating History, Illustration, Quarterly Participation, Monthly Summary, Less Active, Notes, Raw_Data, Player_Game_Log

---

## Summary Report (`build_2026_summaries.py`)

Simpler win/loss stats workbook — no Elo, just raw results for 2026.

Output: `output/pickleball_2026_summary_report.xlsx`

---

## Data

`data/master_history_raw.csv` — the canonical game history file. All scrapes are merged into this file via `merge_csv.py`, which deduplicates before appending.

`data/backups/` — manual snapshots taken before significant data corrections (e.g., player name fixes, deduplication). Safe to leave in place for reference.

---

## Login Session

`den_session.json` stores the Pickleball Den browser session so the scraper can run without manual login. If it stops working:

```bash
rm den_session.json
```

Then rerun and log in manually when the browser opens.

---

## Integration with DEN Assignments

The rating model output (`output/pickleball_model_latest.xlsx`) is read by the DEN Assignments tool to produce the rating-model court assignments alongside the standard DEN assignments.
