# launchd/

Reference copies of the four launchd job definitions that actually run the
SAM ecosystem's scheduled and always-on processes. The **authoritative**
copies live in `~/Library/LaunchAgents/` on this Mac — that's what launchd
actually reads. These are backups for version control and reference only;
editing a file here does **not** change what's running.

## Deploying a change

After editing a plist here, copy it into place and reload the job:

```bash
cp launchd/com.pickleballden.<name>.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.pickleballden.<name>.plist
launchctl load ~/Library/LaunchAgents/com.pickleballden.<name>.plist
```

## The four jobs

| Job | Trigger | What it does |
|---|---|---|
| `signup-monitor` | Every 15 min (`StartInterval`) | Scrapes DEN signup sheets, logs joins/withdrawals/auto-removals, triggers court-assignment + signup-viewer refresh on real changes. |
| `launcher-poller` | Every 5 min (`StartInterval`) | Checks whether today's configured autolaunch time has passed; fires the shootout launcher once per day. |
| `shootout-scraper` | Every 15 min, all day (`StartInterval`) | Runs `run_all.sh` — scrapes game *results* (not signups), rebuilds the rating engine and every public page. Self-gated: `run_all.sh`'s own `SHOULD_SKIP_SCRAPE` logic (8:15 AM MST cutoff, `no_shootout_dates.csv` awareness, "already caught up" check) makes almost every run a cheap no-op except the one that actually finds new results. |
| `launcher-server` | Always running (`KeepAlive`) | The web server behind the Launcher Control Panel dashboard — not scheduled, just kept alive continuously. |

Keeping these in sync with `~/Library/LaunchAgents/` after any change is a
manual step — there's no automated sync for this folder (unlike the
`docs/` HTML pages, which do have automated pushes).
