#!/usr/bin/env python3
"""
patch_avoid_double_logging.py

One-time patch: create_shootout_rating_seeded.py (elo_autolaunch mode)
now logs its own results directly. Without this change, run_launch()
would ALSO log the same result, double-logging every normal
poller-triggered run of that mode. create_shootout.py (step_percent
mode) does NOT yet have self-logging, so this script must keep logging
for that mode exactly as before -- this patch only skips logging when
mode == "elo_autolaunch".

The outer except block (subprocess.run() itself throwing, e.g. a
timeout) still always logs regardless of mode -- if that happens, the
script may have been killed mid-run without ever reaching its own
logging code, so that's the only safety net for that specific case.

Run once from the launcher/ directory:
    python3 patch_avoid_double_logging.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "launcher_poller.py"

OLD_BLOCK = '''        if result.returncode == 0:
            append_log("success", seeding_basis, players_removed,
                        court_assignments=court_assignments,
                        shootout2_shuffle_mode=actual_shuffle_mode or shuffle_label)
            return True
        else:
            append_log("error", seeding_basis, players_removed, shootout2_shuffle_mode=shuffle_label,
                        message=result.stderr[-500:] if result.stderr else "non-zero exit")
            return False'''

NEW_BLOCK = '''        # create_shootout_rating_seeded.py (elo_autolaunch) now logs its
        # own results directly -- confirmed 2026-08-25 this closes a real
        # gap where any direct/manual run of that script never got
        # logged at all. Logging here too would double-log every normal
        # poller-triggered run. create_shootout.py (step_percent) does
        # NOT yet have self-logging, so this script still logs for that
        # mode, same as before.
        already_self_logs = (mode == "elo_autolaunch")

        if result.returncode == 0:
            if not already_self_logs:
                append_log("success", seeding_basis, players_removed,
                            court_assignments=court_assignments,
                            shootout2_shuffle_mode=actual_shuffle_mode or shuffle_label)
            return True
        else:
            if not already_self_logs:
                append_log("error", seeding_basis, players_removed, shootout2_shuffle_mode=shuffle_label,
                            message=result.stderr[-500:] if result.stderr else "non-zero exit")
            return False'''


def main():
    text = TARGET.read_text(encoding="utf-8")
    count = text.count(OLD_BLOCK)
    if count != 1:
        print(f"✗ Aborting: expected exactly 1 match, found {count}. "
              f"File may have already been patched, or changed unexpectedly.")
        return 1
    text = text.replace(OLD_BLOCK, NEW_BLOCK)
    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — no longer double-logs elo_autolaunch runs "
          f"(that script now logs itself); step_percent logging unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
