#!/usr/bin/env python3
"""
patch_log_shuffle_mode.py

One-time patch: the launch log records seeding_basis and court
assignments, but never which "Move Players" shuffle setting
(Two-up/Two-down vs One-up/One-down) was actually configured for that
launch. Adds a human-readable shuffle_mode label to every log entry,
read from launcher_config.json at launch time.

Run once from the launcher/ directory:
    python3 patch_log_shuffle_mode.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "launcher_poller.py"

OLD_LABELS = '''SEEDING_LABELS = {
    "step_percent": "DEN Step/%",
    "elo_autolaunch": "Modified ELO",
}'''

NEW_LABELS = '''SEEDING_LABELS = {
    "step_percent": "DEN Step/%",
    "elo_autolaunch": "Modified ELO",
}

# Matches Den's actual field text (confirmed via live screenshot, not the
# earlier "1-up/1-back/2-stay" terminology used elsewhere in the codebase
# before that correction).
SHUFFLE_LABELS = {
    "2u2b": "Two-up / Two-down",
    "1u1b2s": "One-up / One-down",
}'''

OLD_APPEND_LOG = '''def append_log(status, seeding_basis, players_removed, message="", court_assignments=None):
    entry = {
        "timestamp": datetime.now(MST).strftime("%Y-%m-%d %H:%M:%S MST"),
        "status": status,
        "seeding_basis": seeding_basis,
        "players_removed": players_removed or [],
        "message": message,
        "court_assignments": court_assignments or [],
    }'''

NEW_APPEND_LOG = '''def append_log(status, seeding_basis, players_removed, message="", court_assignments=None, shuffle_mode=None):
    entry = {
        "timestamp": datetime.now(MST).strftime("%Y-%m-%d %H:%M:%S MST"),
        "status": status,
        "seeding_basis": seeding_basis,
        "players_removed": players_removed or [],
        "message": message,
        "court_assignments": court_assignments or [],
        "shuffle_mode": shuffle_mode,
    }'''

OLD_RUN_LAUNCH_TOP = '''def run_launch(mode):
    seeding_basis = SEEDING_LABELS[mode]
    script_path = SCRIPT_PATHS.get(mode)

    if script_path is None:
        append_log("error", seeding_basis, [],
                    message=f"SCRIPT_PATHS['{mode}'] not configured — see TODO in launcher_poller.py")
        return False'''

NEW_RUN_LAUNCH_TOP = '''def run_launch(mode):
    seeding_basis = SEEDING_LABELS[mode]
    script_path = SCRIPT_PATHS.get(mode)
    shuffle_code = load_config().get("shuffle_mode", "2u2b")
    shuffle_label = SHUFFLE_LABELS.get(shuffle_code, shuffle_code)

    if script_path is None:
        append_log("error", seeding_basis, [],
                    message=f"SCRIPT_PATHS['{mode}'] not configured — see TODO in launcher_poller.py",
                    shuffle_mode=shuffle_label)
        return False'''

OLD_SUCCESS_LOG = '''        if result.returncode == 0:
            append_log("success", seeding_basis, players_removed,
                        court_assignments=court_assignments)
            return True
        else:
            append_log("error", seeding_basis, players_removed,'''

NEW_SUCCESS_LOG = '''        if result.returncode == 0:
            append_log("success", seeding_basis, players_removed,
                        court_assignments=court_assignments, shuffle_mode=shuffle_label)
            return True
        else:
            append_log("error", seeding_basis, players_removed, shuffle_mode=shuffle_label,'''


def main():
    text = TARGET.read_text(encoding="utf-8")

    for old, new, label in [
        (OLD_LABELS, NEW_LABELS, "SHUFFLE_LABELS dict"),
        (OLD_APPEND_LOG, NEW_APPEND_LOG, "append_log() signature"),
        (OLD_RUN_LAUNCH_TOP, NEW_RUN_LAUNCH_TOP, "run_launch() top"),
        (OLD_SUCCESS_LOG, NEW_SUCCESS_LOG, "run_launch() success/error branch"),
    ]:
        count = text.count(old)
        if count != 1:
            print(f"✗ Aborting: expected exactly 1 match for {label}, found {count}. "
                  f"File may have already been patched, or changed unexpectedly.")
            return 1
        text = text.replace(old, new)

    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — launch log now records which shuffle "
          f"mode (Two-up/Two-down vs One-up/One-down) was used.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
