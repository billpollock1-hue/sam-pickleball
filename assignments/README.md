# DEN Assignments

Two tools for the Anthem 6 AM Shootout:

1. **Court Assignment Generator** — scrapes the signup sheet and produces a court assignment PDF
2. **Signup Monitor** — runs silently in the background every 15 minutes, logging who joins and withdraws from each upcoming session

---

## Directory Structure

```
DEN Assignments/
├── den_assignments.py          # Court assignment script
├── Run DEN Assignments.command # Double-click launcher
├── monitor_signups.py          # Signup monitor (symlink → PBMonitor)
├── signup_monitor_state.json   # Monitor state (symlink → PBMonitor)
├── den_session.json            # Saved Pickleball Den login session
├── .venv/                      # Python virtual environment
├── logs/                       # Signup change logs (symlink → PBMonitor/logs)
│   ├── YYYY-MM-DD_signup_log.csv
│   ├── monitor_stdout.log
│   └── monitor_stderr.log
└── output/                     # Court assignment PDFs
    └── YYYY-MM-DD_6AM_Court_Assignments.pdf
```

---

## Court Assignment Generator

### Running It

**Option 1 — Recommended:** Double-click `Run DEN Assignments.command`

**Option 2 — Terminal:**
```
cd ~/Documents/"SAM Pickleball/DEN Assignments"
.venv/bin/python3 den_assignments.py
```

### What It Does

1. Opens Pickleball Den in a browser (reuses saved session if available)
2. Navigates to the Sign-Up Sheet View and searches for the target date
3. Waits for you to confirm the right sheet is showing
4. Scrapes the signup list
5. Assigns players to courts using two methods:
   - **DEN method:** Step (ascending) then Percent (descending)
   - **Rating model:** Elo-style rating from PickleballModel
6. Generates a multi-page PDF:
   - Page 1 — DEN court assignments
   - Page 2 — Rating model assignments
   - Page 3 — Side-by-side comparison
7. Opens the PDF automatically

### Court Assignment Logic

Players are eligible in signup order. Extra players (beyond the nearest multiple of 4) go to the waitlist.

**DEN method ranking:** Step ascending, then Percent descending within the same Step.

**Rating model ranking:** Elo-based player rating descending (higher rating = higher court).

`DEN New Player Tryout` is always placed at the bottom of eligible players regardless of rating.

### Output

PDFs are saved to `output/` with the session date in the filename:
```
output/2026-07-01_6AM_Court_Assignments.pdf
```

### Login Session

The saved session in `den_session.json` keeps you logged in across runs. If login stops working, delete it and log in manually on the next run:
```
rm den_session.json
```

---

## Signup Monitor

Runs automatically every 15 minutes via a macOS launchd agent. No manual action required.

### What It Tracks

- **Joins** — when a player signs up for a session
- **Withdrawals** — when a player removes themselves
- **Reorders** — signup positions that shift after a withdrawal
- **New sheets** — when a new batch of session dates is posted (usually Thursday or Friday)

### Log Files

One CSV per session date in `logs/`:
```
logs/2026-07-01_signup_log.csv
```

Columns: `timestamp_mt`, `action`, `player`, `signup_order`, `prior_order`

Actions:
- `joined*` — player was on the sheet when it was first discovered
- `joined` — player signed up after first discovery
- `withdrew` — player removed themselves
- `reordered` — player's signup position changed due to a withdrawal above them

Monitoring stops for a given date at 8:00 AM MT on the session day.

### New Sheet Notifications

A macOS notification is sent when new session dates appear on the signup page.

### Technical Details

The monitor is managed by launchd:
```
~/Library/LaunchAgents/com.pickleballden.signup-monitor.plist
```

The `logs/`, `monitor_signups.py`, and `signup_monitor_state.json` entries in this folder are symlinks pointing to the actual files in `~/Library/Application Support/PBMonitor/`, where launchd can access them.

---

## Troubleshooting

**Browser opens but script hangs** — make sure View Players is expanded on the correct sheet, then press Return in the terminal.

**Login fails** — delete `den_session.json` and rerun; log in manually when prompted.

**Monitor not running** — check:
```
launchctl list | grep pickleball
```
A `-` in the PID column is normal (job ran and exited). Exit code `0` = success.

**Suspicious log entries** — if you see every player withdrawing and rejoining within one polling cycle, that's a session-expiry artifact. The monitor now detects this automatically and skips logging it.
