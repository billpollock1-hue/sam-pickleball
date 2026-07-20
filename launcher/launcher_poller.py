#!/usr/bin/env python3
"""
launcher_poller.py

Invoked every 5 minutes by launchd (StartInterval=300). Checks
launcher_config.json; if mode is "step_percent" or "elo_autolaunch" and
current MST time has reached autolaunch_time_mst and we haven't already
auto-launched today, fires the corresponding shootout creation script and
logs the result.

This intentionally does NOT run as a long-lived sleeping process — polling
is resilient to the Mac sleeping/waking or the process being killed, matching
the hash-based skip-logic approach already used in run_all.sh (recompute
"should I act?" from state on disk every time, rather than trusting an
in-memory timer).

Log retention: launch_log.jsonl is trimmed to the last LOG_RETENTION_DAYS
days on every append, oldest entries first (matching the file's own
chronological write order) -- the control panel's own display already
reverses this to newest-first, so trimming the old end of the file never
disturbs what's currently visible without scrolling.
"""

import json
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "launcher_config.json"
LOG_PATH = BASE_DIR / "launch_log.jsonl"
MST = ZoneInfo("America/Phoenix")  # Arizona, no DST — matches "MST" label used everywhere else

LOG_RETENTION_DAYS = 30

SCRIPT_PATHS = {
    "step_percent": str(Path.home() / "Documents/SAM Pickleball/sam-pickleball/assignments/create_shootout.py"),
    "elo_autolaunch": str(Path.home() / "Documents/SAM Pickleball/sam-pickleball/assignments/create_shootout_rating_seeded.py"),
}

SEEDING_LABELS = {
    "step_percent": "DEN Step/%",
    "elo_autolaunch": "Modified ELO",
}


def load_config():
    if not CONFIG_PATH.exists():
        return {"mode": "none", "autolaunch_time_mst": "05:45", "last_autolaunch_date": None}
    return json.loads(CONFIG_PATH.read_text())


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def append_log(status, seeding_basis, players_removed, message=""):
    entry = {
        "timestamp": datetime.now(MST).strftime("%Y-%m-%d %H:%M:%S MST"),
        "status": status,
        "seeding_basis": seeding_basis,
        "players_removed": players_removed or [],
        "message": message,
    }
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    _trim_old_entries()
    return entry


def _trim_old_entries():
    """
    Keep only the last LOG_RETENTION_DAYS days of entries. Reads the whole
    file, drops anything older than the cutoff, rewrites it. Malformed
    lines (shouldn't happen, but defensive) are dropped rather than
    crashing the trim.
    """
    if not LOG_PATH.exists():
        return
    cutoff = datetime.now(MST) - timedelta(days=LOG_RETENTION_DAYS)
    try:
        lines = LOG_PATH.read_text().splitlines()
    except Exception:
        return

    kept = []
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            ts = datetime.strptime(entry["timestamp"], "%Y-%m-%d %H:%M:%S MST").replace(tzinfo=MST)
            if ts >= cutoff:
                kept.append(line)
        except Exception:
            continue  # drop unparseable lines rather than erroring the whole trim

    if len(kept) != len(lines):
        LOG_PATH.write_text("\n".join(kept) + ("\n" if kept else ""))


def run_launch(mode):
    seeding_basis = SEEDING_LABELS[mode]
    script_path = SCRIPT_PATHS.get(mode)

    if script_path is None:
        append_log("error", seeding_basis, [],
                    message=f"SCRIPT_PATHS['{mode}'] not configured — see TODO in launcher_poller.py")
        return False

    try:
        result = subprocess.run(
            ["python3", str(script_path)],
            capture_output=True, text=True, timeout=600,
            cwd=str(Path(script_path).parent),
        )
        players_removed = []
        match = re.search(r"LAUNCH_RESULT:\s*(\{.*\})", result.stdout)
        if match:
            try:
                players_removed = json.loads(match.group(1)).get("players_removed", [])
            except json.JSONDecodeError:
                pass

        if result.returncode == 0:
            append_log("success", seeding_basis, players_removed)
            return True
        else:
            append_log("error", seeding_basis, players_removed,
                        message=result.stderr[-500:] if result.stderr else "non-zero exit")
            return False
    except Exception as e:
        append_log("error", seeding_basis, [], message=str(e))
        return False


def main():
    cfg = load_config()
    mode = cfg.get("mode")
    if mode not in ("step_percent", "elo_autolaunch"):
        return

    now = datetime.now(MST)
    today_str = now.date().isoformat()

    if cfg.get("last_autolaunch_date") == today_str:
        return  # already launched today

    target_str = cfg.get("autolaunch_time_mst", "05:45")
    target_h, target_m = (int(x) for x in target_str.split(":"))
    target_dt = now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)

    # Guard against firing immediately on a fresh launchd load (or right after
    # hitting Save) just because today's target time already passed earlier
    # today. Only auto-fire "late" if the config was actually in place before
    # the target time -- otherwise wait for tomorrow's natural crossing.
    updated_at_str = cfg.get("updated_at")
    if updated_at_str:
        try:
            updated_at = datetime.fromisoformat(updated_at_str)
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=MST)
            updated_at_mst = updated_at.astimezone(MST)
            if updated_at_mst.date() == now.date() and updated_at_mst > target_dt:
                return  # enabled/saved after today's target already passed
        except Exception:
            pass

    if now >= target_dt:
        succeeded = run_launch(mode)
        if succeeded:
            cfg["last_autolaunch_date"] = today_str
            save_config(cfg)


if __name__ == "__main__":
    main()
