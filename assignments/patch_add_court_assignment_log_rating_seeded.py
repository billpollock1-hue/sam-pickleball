#!/usr/bin/env python3
"""
patch_add_court_assignment_log_rating_seeded.py

One-time patch: same idea as patch_add_court_assignment_log.py, but for
the Modified ELO / rating-seeded launcher variant. Captures each player's
REAL model Rating and final court assignment into LAUNCH_RESULT, before
Step gets overwritten with the synthetic court-based value used for the
seeding audit.

Run once from the assignments/ directory:
    python3 patch_add_court_assignment_log_rating_seeded.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "create_shootout_rating_seeded.py"

OLD_CAPTURE = '''            computed_assignments = rating_assignments.copy()
            computed_assignments["Step"] = (
                computed_assignments["Court"] - computed_assignments["Court"].min() + 1
            )'''

NEW_CAPTURE = '''            computed_assignments = rating_assignments.copy()

            # Capture each player's REAL model Rating + final court
            # assignment for the launch log, before Step gets overwritten
            # below with a synthetic court-based value for the seeding audit.
            court_assignments_log = [
                {
                    "player": clean_name(r["Player"]),
                    "rating": (None if pd.isna(r["Rating"]) else round(float(r["Rating"]))),
                    "court": int(r["Court"]),
                }
                for _, r in computed_assignments.sort_values(["Court", "CourtPosition"]).iterrows()
            ]

            computed_assignments["Step"] = (
                computed_assignments["Court"] - computed_assignments["Court"].min() + 1
            )'''

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
          f"real model Rating and final court.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
