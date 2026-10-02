#!/usr/bin/env python3
"""
Patch: assignments/create_shootout_rating_seeded.py's seeding audit now
correctly handles a recorded tryout-name identification (data/
tryout_name_fixes.csv) against Den's own live page.

Real gap found 2026-10-01, before ever actually occurring in production:
computed_assignments already has the tryout slot's real name substituted
in (e.g. "Dean Parks", via den_assignments.py's existing substitution --
unrelated to this bug and already working correctly). But Den's own
Ladder Step grid page still literally displays "Den New Player Tryout"
for that row -- the substitution only ever existed in our own data, never
on Den's site. read_ladder_step_grid() matched grid text only against
known_player_names (the substituted names), so that one row's text never
matched. Traced the full consequence: ordered_names comes up one short of
step_count, which trips the existing "counts don't line up -- skipping
audit" safety check, retries twice via the (unrelated) under-render retry
path, and finally returns empty -- silently skipping the Step-correction
audit for the ENTIRE grid, not just the tryout player, with only a log
warning, nothing that stops the run.

Fix: read_ladder_step_grid() and cross_check_and_correct_seeding() now
accept an optional tryout_fix_name. When a grid cell's text doesn't match
a known player name but does match Den's raw placeholder text
("den new player tryout", case-insensitive prefix match -- matching the
pattern already used for this exact label elsewhere in den_assignments.py,
since the live page may append its own annotation), the row is recorded
under the SUBSTITUTED name instead, so it lines up with
computed_assignments exactly like every other row. Positional pairing
with the Step inputs (zip by index) is unaffected either way.

Run once from the repo root: python3 sam_fix_tryout_name_step_audit.py
Safe to re-run: asserts each anchor matches exactly once.
"""
from pathlib import Path

path = Path("assignments/create_shootout_rating_seeded.py")
content = path.read_text()


def replace_once(text, old, new, label):
    n = text.count(old)
    assert n == 1, f"{label}: expected exactly 1 match, found {n}"
    return text.replace(old, new)


# 1. Import load_tryout_name_fix alongside the other den_assignments imports.
old1 = "    assign_courts_by_rating,\n    load_player_ratings,\n"
new1 = "    assign_courts_by_rating,\n    load_player_ratings,\n    load_tryout_name_fix,\n"
content = replace_once(content, old1, new1, "import")

# 2. read_ladder_step_grid(): accept tryout_fix_name, and fall back to it
#    for a grid cell still showing Den's raw placeholder text.
old2 = (
    "def read_ladder_step_grid(page, known_player_names):"
)
new2 = (
    "def read_ladder_step_grid(page, known_player_names, tryout_fix_name=None):"
)
content = replace_once(content, old2, new2, "function signature")

old3 = (
    '    ordered_names = []\n'
    '    for i in range(name_cell_count):\n'
    '        try:\n'
    '            text = clean_name(name_cells.nth(i).inner_text())\n'
    '        except Exception:\n'
    '            continue\n'
    '        if text and text in known_player_names:\n'
    '            ordered_names.append(text)\n'
)
new3 = (
    '    ordered_names = []\n'
    '    for i in range(name_cell_count):\n'
    '        try:\n'
    '            text = clean_name(name_cells.nth(i).inner_text())\n'
    '        except Exception:\n'
    '            continue\n'
    '        if text and text in known_player_names:\n'
    '            ordered_names.append(text)\n'
    '        elif tryout_fix_name and text.lower().startswith("den new player tryout"):\n'
    '            # Den\'s own page still shows the raw placeholder text for\n'
    '            # this row -- the real-name substitution only ever existed\n'
    '            # in our own computed data, never on Den\'s site. Record it\n'
    '            # under the substituted name so it lines up with\n'
    '            # computed_assignments exactly like every other row.\n'
    '            ordered_names.append(tryout_fix_name)\n'
)
content = replace_once(content, old3, new3, "matching loop")

# 3. cross_check_and_correct_seeding(): accept date_str, look up the fix
#    once, and pass it through both read_ladder_step_grid() call sites
#    (the initial read and the under-render retry read).
old4 = "def cross_check_and_correct_seeding(page, computed_assignments):"
new4 = "def cross_check_and_correct_seeding(page, computed_assignments, date_str=None):"
content = replace_once(content, old4, new4, "cross_check signature")

old5 = (
    '    known_player_names = set(computed_assignments["Player"].apply(clean_name))\n'
    '    expected_count = len(computed_assignments)\n'
    '\n'
    '    grid = read_ladder_step_grid(page, known_player_names)\n'
)
new5 = (
    '    known_player_names = set(computed_assignments["Player"].apply(clean_name))\n'
    '    expected_count = len(computed_assignments)\n'
    '    tryout_fix_name = load_tryout_name_fix(date_str) if date_str else None\n'
    '\n'
    '    grid = read_ladder_step_grid(page, known_player_names, tryout_fix_name)\n'
)
content = replace_once(content, old5, new5, "initial grid read")

old6 = (
    '        page.wait_for_timeout(2000 + attempts * 1000)\n'
    '        grid = read_ladder_step_grid(page, known_player_names)\n'
)
new6 = (
    '        page.wait_for_timeout(2000 + attempts * 1000)\n'
    '        grid = read_ladder_step_grid(page, known_player_names, tryout_fix_name)\n'
)
content = replace_once(content, old6, new6, "retry grid read")

# 4. Pass play_date_file through at the actual call site.
old7 = "            cross_check_and_correct_seeding(page, computed_assignments)\n"
new7 = "            cross_check_and_correct_seeding(page, computed_assignments, play_date_file)\n"
content = replace_once(content, old7, new7, "call site")

path.write_text(content)
print("create_shootout_rating_seeded.py updated successfully")
