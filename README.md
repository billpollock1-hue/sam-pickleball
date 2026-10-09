# SAM Pickleball

One system for the Anthem SAM 6 AM Shootout: scrape results from Pickleball Den,
rate players with a modified Elo model, publish charts and a session viewer to
GitHub Pages, generate daily court assignments, and monitor signups.

Live pages: https://billpollock1-hue.github.io/sam-pickleball/session_viewer.html

---

## Directory Map

```
sam-pickleball/
├── Run Model.command           # One click: scrape → rate → publish (opens workbook)
├── Run Assignments.command     # One click: generate today's court assignments PDF
├── Open Charts.command         # Opens the four HTML charts locally
├── run_all.sh                  # The pipeline behind Run Model.command
│
├── engine/                     # Rating model & report builders
│   ├── pickleball_engine_v2.py     # Core modified-Elo engine + Excel workbook
│   ├── build_session_viewer.py     # Per-date rating-change viewer (HTML)
│   └── build_2026_summaries.py     # Win/loss stats workbook (no Elo)
│
├── scraper/                    # Getting data out of Pickleball Den
│   ├── scrape.js                   # Playwright scraper (shootout scores)
│   ├── merge_csv.py                # Dedupes new scrapes into master history
│   ├── den_config.json             # Saved Club Play List URL
│   ├── den_credentials.json        # Auto-login credentials (gitignored)
│   └── den_session.json            # Saved login session (gitignored)
│
├── assignments/                # Daily court assignments
│   ├── den_assignments.py          # Builds assignments from ratings + signups → PDF
│   ├── generate_assignments_viewer.py  # HTML history viewer of past assignments
│   └── output/assignments_history/     # JSON snapshot per play date
│
├── signup-monitor/             # Background signup watcher (launchd, every 15 min)
│   ├── monitor_signups.py          # Source of truth — deploy with setup_monitor.sh
│   ├── generate_signup_viewer.py   # Signup viewer HTML builder
│   ├── setup_monitor.sh            # Deploys source → ~/Library/App Support/PBMonitor
│   ├── install_monitor.sh          # Installs/uninstalls the launchd agent
│   └── run_monitor.sh              # Manually trigger one monitor pass
│
├── data/                       # Master game history (CSV) + backups
├── docs/                       # What GitHub Pages serves — synced by run_all.sh
├── output/                     # Generated workbooks & HTML (rebuilt every run)
└── tools/                      # Occasional utilities
```

## Normal Workflow

- **After a play date:** double-click `Run Model.command` — scrapes, rebuilds
  ratings, updates the published pages, opens the workbook.
- **Before a play date:** double-click `Run Assignments.command` — refreshes
  data if needed, generates the court assignments PDF in `assignments/`.
- The signup monitor runs itself; edit its source here, then re-run
  `signup-monitor/setup_monitor.sh` followed by `install_monitor.sh` to deploy.
