Pickleball Model System

Main folder:
~/Documents/PickleballModel/

Active files:
scrape.js                  = pulls latest shootout data
pickleball_engine_v2.py    = ratings / leaderboard model
build_2026_summaries.py    = analytics / summaries
analyze_patterns.py        = additional pattern analysis, if used

Folders:
data/      = master_history_raw.csv and latest_scrape.csv
output/    = generated Excel workbooks

Usual commands:
cd ~/Documents/PickleballModel
./run_all.sh

Ratings output:
output/pickleball_model_latest.xlsx

Summary output:
output/pickleball_2026_summary_report.xlsx
