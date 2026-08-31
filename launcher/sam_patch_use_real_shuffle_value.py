#!/usr/bin/env python3
"""
patch_use_real_shuffle_value.py

One-time patch: run_launch() logged shuffle_label (what was CONFIGURED)
unconditionally, even on success, even though both create_shootout.py
and create_shootout_rating_seeded.py now report the ACTUAL observed
value in LAUNCH_RESULT (2026-08-24 patches). Extracts that real value
and prefers it on success, falling back to the configured label only
when it's genuinely unavailable (e.g. the already-exists guard path,
or an older script that doesn't report it).

Run once from the launcher/ directory:
    python3 patch_use_real_shuffle_value.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "launcher_poller.py"

OLD_BLOCK = '''        players_removed = []
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
                        court_assignments=court_assignments, shootout2_shuffle_mode=shuffle_label)
            return True'''

NEW_BLOCK = '''        players_removed = []
        court_assignments = []
        actual_shuffle_mode = None
        match = re.search(r"LAUNCH_RESULT:\\s*(\\{.*\\})", result.stdout)
        if match:
            try:
                launch_result = json.loads(match.group(1))
                players_removed = launch_result.get("players_removed", [])
                court_assignments = launch_result.get("court_assignments", [])
                actual_shuffle_mode = launch_result.get("shootout2_shuffle_mode")
            except json.JSONDecodeError:
                pass

        if result.returncode == 0:
            append_log("success", seeding_basis, players_removed,
                        court_assignments=court_assignments,
                        shootout2_shuffle_mode=actual_shuffle_mode or shuffle_label)
            return True'''


def main():
    text = TARGET.read_text(encoding="utf-8")
    count = text.count(OLD_BLOCK)
    if count != 1:
        print(f"✗ Aborting: expected exactly 1 match, found {count}. "
              f"File may have already been patched, or changed unexpectedly.")
        return 1
    text = text.replace(OLD_BLOCK, NEW_BLOCK)
    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — successful launches now log the real "
          f"observed shuffle value, not just what was configured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
