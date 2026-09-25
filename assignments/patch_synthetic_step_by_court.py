#!/usr/bin/env python3
"""
patch_synthetic_step_by_court.py

One-time patch: create_shootout.py's seeding audit (cross_check_and_
correct_seeding) was comparing DEN's live Step value against each
player's own REAL DEN Step (unchanged from assign_courts()'s ranking
step) -- meaning the "correction" just re-synced each player's own
individual Step number, which does nothing to force DEN's own Seed
Players grouping to match the actual 4-per-court split, since multiple
real Step values routinely land inside the same computed court group.

Fix: convert each player's Step to a synthetic, purely court-based value
right where create_shootout.py builds its own computed_assignments --
Court 1's four players all get Step 1, Court 2's four get Step 2, and so
on, irrespective of their real DEN Step. Same technique already used in
create_shootout_rating_seeded.py.

Deliberately scoped to create_shootout.py's own local copy of
computed_assignments only -- den_assignments.py's assign_courts()
(shared with generate_assignments_viewer.py, which still needs each
player's REAL Step/% for display) is untouched.

Run once from the assignments/ directory:
    python3 patch_synthetic_step_by_court.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "create_shootout.py"

OLD_BLOCK = '''            eligible_signups = signups.iloc[:eligible_count].copy()
            computed_assignments, _ = assign_courts(eligible_signups, ratings)

            # Back to the signup sheet to actually create the shootout.'''

NEW_BLOCK = '''            eligible_signups = signups.iloc[:eligible_count].copy()
            computed_assignments, _ = assign_courts(eligible_signups, ratings)

            # Convert each player's REAL DEN Step to a synthetic, purely
            # court-based value before the seeding audit -- Court 1's four
            # players all get Step 1, Court 2's four get Step 2, and so on,
            # irrespective of their real Step. DEN's own Seed Players action
            # groups strictly by matching Step value, so auditing against
            # each player's real (individual) Step -- as this used to do --
            # left multiple real Step values sitting inside the same
            # computed court group, which DEN would then seed incorrectly.
            # Same technique already used in create_shootout_rating_seeded.py.
            # Local to this script's own copy only -- assign_courts() itself
            # (shared with generate_assignments_viewer.py's real Step/%
            # display) is untouched.
            computed_assignments["Step"] = (
                computed_assignments["Court"] - computed_assignments["Court"].min() + 1
            )

            # Back to the signup sheet to actually create the shootout.'''


def main():
    text = TARGET.read_text(encoding="utf-8")
    count = text.count(OLD_BLOCK)
    if count != 1:
        print(f"✗ Aborting: expected exactly 1 match, found {count}. "
              f"File may have already been patched, or changed unexpectedly.")
        return 1
    text = text.replace(OLD_BLOCK, NEW_BLOCK)
    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — seeding audit now uses a synthetic "
          f"court-based Step value instead of each player's real Step.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
