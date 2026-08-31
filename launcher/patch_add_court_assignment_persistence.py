#!/usr/bin/env python3
"""
patch_add_court_assignment_persistence.py

One-time patch: launcher_poller.py previously only extracted
players_removed from a successful launch's LAUNCH_RESULT output, and
append_log() had no field for anything beyond that -- meaning the actual
per-player court assignment detail (real DEN Step/% or model Rating,
plus final court) that create_shootout.py now computes and prints was
captured for a few seconds in the subprocess's stdout, then discarded.

Run once from the launcher/ directory:
    python3 patch_add_court_assignment_persistence.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "launcher_poller.py"

OLD_APPEND_LOG = '''def append_log(status, seeding_basis, players_removed, message=""):
    entry = {
        "timestamp": datetime.now(MST).strftime("%Y-%m-%d %H:%M:%S MST"),
        "status": status,
        "seeding_basis": seeding_basis,
        "players_removed": players_removed or [],
        "message": message,
    }'''

NEW_APPEND_LOG = '''def append_log(status, seeding_basis, players_removed, message="", court_assignments=None):
    entry = {
        "timestamp": datetime.now(MST).strftime("%Y-%m-%d %H:%M:%S MST"),
        "status": status,
        "seeding_basis": seeding_basis,
        "players_removed": players_removed or [],
        "message": message,
        "court_assignments": court_assignments or [],
    }'''

OLD_RUN_LAUNCH = '''        players_removed = []
        match = re.search(r"LAUNCH_RESULT:\\s*(\\{.*\\})", result.stdout)
        if match:
            try:
                players_removed = json.loads(match.group(1)).get("players_removed", [])
            except json.JSONDecodeError:
                pass

        if result.returncode == 0:
            append_log("success", seeding_basis, players_removed)
            return True'''

NEW_RUN_LAUNCH = '''        players_removed = []
        court_assignments = []
        match = re.search(r"LAUNCH_RESULT:\\s*(\\{.*\\})", result.stdout)
        if match:
            try:
                launch_result = json.loads(match.group(1))
                players_removed = launch_result.get("players_removed", [])
                court_assignments = launch_result.get("court_assignments", [])
            except json.JSONDecodeError:
                pass

        if result.returncode == 0:
            append_log("success", seeding_basis, players_removed,
                        court_assignments=court_assignments)
            return True'''


def main():
    text = TARGET.read_text(encoding="utf-8")

    for old, new, label in [
        (OLD_APPEND_LOG, NEW_APPEND_LOG, "append_log() signature"),
        (OLD_RUN_LAUNCH, NEW_RUN_LAUNCH, "run_launch() success path"),
    ]:
        count = text.count(old)
        if count != 1:
            print(f"✗ Aborting: expected exactly 1 match for {label}, found {count}. "
                  f"File may have already been patched, or changed unexpectedly.")
            return 1
        text = text.replace(old, new)

    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — successful launches now persist each "
          f"player's court assignment detail in launch_log.jsonl.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
