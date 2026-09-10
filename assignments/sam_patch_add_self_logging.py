#!/usr/bin/env python3
"""
patch_add_self_logging.py

One-time patch: logging was previously the poller's exclusive
responsibility -- meaning any direct/manual run of this script (e.g.
live testing) never got logged at all, a real gap confirmed live
2026-08-25 (three genuine test successes that morning, invisible in the
log). Moves logging into the script itself, so the same honest record
gets kept whether the scheduled poller invoked it or a person ran it
directly by hand.

Run once from the assignments/ directory:
    python3 patch_add_self_logging.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "create_shootout_rating_seeded.py"

OLD_IMPORT = "from datetime import datetime"
NEW_IMPORT = "from datetime import datetime, timedelta"

OLD_FUNC_START = "def create_shootout(page, num_courts):"
NEW_FUNC_START = '''# Absolute path -- same reasoning as LAUNCHER_CONFIG_PATH above: this
# script always runs from assignments/, but the shared launch log
# always lives in launcher/, regardless of which copy of this script
# is running, and regardless of whether the poller or a person invoked
# it directly.
LAUNCH_LOG_PATH = Path(
    "/Users/billpollock/Documents/SAM Pickleball/sam-pickleball/launcher/launch_log.jsonl"
)
LOG_RETENTION_DAYS = 30  # matches launcher_poller.py's own retention window


def log_launch_result(status, players_removed, message="", court_assignments=None,
                       shootout2_shuffle_mode=None):
    """
    Writes directly to the shared launch log, regardless of whether this
    script was invoked by the scheduled poller or run directly by hand.
    Never lets a logging failure crash the actual launch.
    """
    entry = {
        "timestamp": datetime.now(ZoneInfo("America/Phoenix")).strftime("%Y-%m-%d %H:%M:%S MST"),
        "status": status,
        "seeding_basis": "Modified ELO",
        "players_removed": players_removed or [],
        "message": message,
        "court_assignments": court_assignments or [],
        "shootout2_shuffle_mode": shootout2_shuffle_mode,
    }
    try:
        with LAUNCH_LOG_PATH.open("a") as f:
            f.write(json.dumps(entry) + "\\n")
        _trim_launch_log()
    except Exception:
        pass


def _trim_launch_log():
    if not LAUNCH_LOG_PATH.exists():
        return
    cutoff = datetime.now(ZoneInfo("America/Phoenix")) - timedelta(days=LOG_RETENTION_DAYS)
    try:
        lines = LAUNCH_LOG_PATH.read_text().splitlines()
    except Exception:
        return
    kept = []
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            ts = datetime.strptime(entry["timestamp"], "%Y-%m-%d %H:%M:%S MST").replace(
                tzinfo=ZoneInfo("America/Phoenix")
            )
            if ts >= cutoff:
                kept.append(line)
        except Exception:
            continue
    if len(kept) != len(lines):
        LAUNCH_LOG_PATH.write_text("\\n".join(kept) + ("\\n" if kept else ""))


def create_shootout(page, num_courts):'''

OLD_TRY_START = '''        try:
            print("Opening signup sheet...")'''

NEW_TRY_START = '''        excess_names = []
        court_assignments_log = []
        actual_shuffle_mode = None
        try:
            print("Opening signup sheet...")'''

OLD_SUCCESS = '''            print(f"LAUNCH_RESULT: {json.dumps({'players_removed': excess_names, 'court_assignments': court_assignments_log, 'shootout2_shuffle_mode': actual_shuffle_mode})}")

        except Exception as e:
            print(f"\\n✗ Automated shootout creation failed: {e}")
            _debug_screenshot(page, "fatal_failure")
            raise'''

NEW_SUCCESS = '''            print(f"LAUNCH_RESULT: {json.dumps({'players_removed': excess_names, 'court_assignments': court_assignments_log, 'shootout2_shuffle_mode': actual_shuffle_mode})}")
            log_launch_result("success", excess_names, court_assignments=court_assignments_log,
                               shootout2_shuffle_mode=actual_shuffle_mode)

        except Exception as e:
            print(f"\\n✗ Automated shootout creation failed: {e}")
            log_launch_result("error", excess_names, message=str(e),
                               court_assignments=court_assignments_log,
                               shootout2_shuffle_mode=actual_shuffle_mode)
            _debug_screenshot(page, "fatal_failure")
            raise'''


def main():
    text = TARGET.read_text(encoding="utf-8")

    for old, new, label in [
        (OLD_IMPORT, NEW_IMPORT, "datetime import"),
        (OLD_FUNC_START, NEW_FUNC_START, "logging functions"),
        (OLD_TRY_START, NEW_TRY_START, "try-block variable init"),
        (OLD_SUCCESS, NEW_SUCCESS, "success/error logging calls"),
    ]:
        count = text.count(old)
        if count != 1:
            print(f"✗ Aborting: expected exactly 1 match for {label}, found {count}. "
                  f"File may have already been patched, or changed unexpectedly.")
            return 1
        text = text.replace(old, new)

    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — this script now logs its own results directly, "
          f"regardless of whether the poller or a person invoked it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
