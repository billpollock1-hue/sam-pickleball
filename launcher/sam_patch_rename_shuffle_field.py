#!/usr/bin/env python3
"""
patch_rename_shuffle_field.py

One-time patch: renames the log field "shuffle_mode" to
"shootout2_shuffle_mode" -- this setting is configured on the Shootout 1
creation form (it's the only "Move Players" field that exists), but it
governs Den's Shootout 2 movement behavior specifically. The old generic
name could be ambiguous to someone reading raw log data without that
context; the new name is unambiguous at a glance.

Run once from the launcher/ directory:
    python3 patch_rename_shuffle_field.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "launcher_poller.py"

REPLACEMENTS = [
    (
        'def append_log(status, seeding_basis, players_removed, message="", court_assignments=None, shuffle_mode=None):',
        'def append_log(status, seeding_basis, players_removed, message="", court_assignments=None, shootout2_shuffle_mode=None):',
    ),
    (
        '        "shuffle_mode": shuffle_mode,',
        '        "shootout2_shuffle_mode": shootout2_shuffle_mode,',
    ),
    (
        '                    shuffle_mode=shuffle_label)',
        '                    shootout2_shuffle_mode=shuffle_label)',
    ),
    (
        '                        court_assignments=court_assignments, shuffle_mode=shuffle_label)',
        '                        court_assignments=court_assignments, shootout2_shuffle_mode=shuffle_label)',
    ),
    (
        '            append_log("error", seeding_basis, players_removed, shuffle_mode=shuffle_label,',
        '            append_log("error", seeding_basis, players_removed, shootout2_shuffle_mode=shuffle_label,',
    ),
]


def main():
    text = TARGET.read_text(encoding="utf-8")

    for old, new in REPLACEMENTS:
        count = text.count(old)
        if count != 1:
            print(f"✗ Aborting: expected exactly 1 match for:\n  {old!r}\n"
                  f"found {count}. File may have already been patched, or changed unexpectedly.")
            return 1
        text = text.replace(old, new)

    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — log field renamed shuffle_mode -> shootout2_shuffle_mode.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
