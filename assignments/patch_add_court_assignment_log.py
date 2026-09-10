#!/usr/bin/env python3
"""
patch_add_court_assignment_log.py

One-time patch: captures each player's REAL DEN Step/% and final court
assignment into LAUNCH_RESULT, before Step gets overwritten with the
synthetic court-based value used for the seeding audit (see
patch_synthetic_step_by_court.py, applied earlier). Without this, that
real per-player detail was computed but never persisted anywhere --
launcher_poller.py only ever logs players_removed, even on success.

Run once from the assignments/ directory:
    python3 patch_add_court_assignment_log.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "create_shootout.py"

OLD_CAPTURE = '''            eligible_signups = signups.iloc[:eligible_count].copy()
            computed_assignments, _ = assign_courts(eligible_signups, ratings)

            # Convert each player's REAL DEN Step to a synthetic, purely'''

NEW_CAPTURE = '''            eligible_signups = signups.iloc[:eligible_count].copy()
            computed_assignments, _ = assign_courts(eligible_signups, ratings)

            # Capture each player's REAL DEN Step/% + final court assignment
            # for the launch log, before Step gets overwritten below with a
            # synthetic court-based value for the seeding audit.
            court_assignments_log = [
                {
                    "player": clean_name(r["Player"]),
                    "den_step": (None if pd.isna(r["Step"]) else int(r["Step"])),
                    "den_pct": (None if pd.isna(r["Percent"]) else round(float(r["Percent"]), 1)),
                    "court": int(r["Court"]),
                }
                for _, r in computed_assignments.sort_values(["Court", "CourtPosition"]).iterrows()
            ]

            # Convert each player's REAL DEN Step to a synthetic, purely'''

OLD_RESULT = '''            print(f"LAUNCH_RESULT: {json.dumps({'players_removed': excess_names})}")'''

NEW_RESULT = '''            print(f"LAUNCH_RESULT: {json.dumps({'players_removed': excess_names, 'court_assignments': court_assignments_log})}")'''


def main():
    text = TARGET.read_text(encoding="utf-8")

    for old, new, label in [
        (OLD_CAPTURE, NEW_CAPTURE, "court-assignment capture"),
        (OLD_RESULT, NEW_RESULT, "LAUNCH_RESULT line"),
    ]:
        count = text.count(old)
        if count != 1:
            print(f"✗ Aborting: expected exactly 1 match for {label}, found {count}. "
                  f"File may have already been patched, or changed unexpectedly.")
            return 1
        text = text.replace(old, new)

    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — LAUNCH_RESULT now includes each player's "
          f"real DEN Step/% and final court.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
