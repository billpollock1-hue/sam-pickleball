#!/usr/bin/env python3
"""
One-off patch: adds a GET /api/recorded-dates endpoint to
launcher_server.py, powering a new log section on the "Record a Date"
admin page. Reads both NO_SHOOTOUT_CSV and PARTIAL_SHOOTOUT_CSV,
tags each entry with its type, and returns them combined and sorted
newest-first (YYYY-MM-DD strings sort correctly as plain strings, no
date parsing needed).

Run once from the repo root: python3 sam_add_recorded_dates_endpoint.py
Safe to re-run: asserts each anchor matches exactly once.
"""
from pathlib import Path

path = Path("launcher/launcher_server.py")
content = path.read_text()

# 1. Add the new route, right after /api/next-shootout (a simple,
#    already-working GET route to sit next to).
anchor1 = (
    '        elif self.path == "/api/next-shootout":\n'
    '            self._send_json({"display": get_next_shootout_display()})'
)
assert content.count(anchor1) == 1, f"anchor1 matches: {content.count(anchor1)}"
new1 = anchor1 + (
    '\n        elif self.path == "/api/recorded-dates":\n'
    '            self._send_json(get_recorded_dates())'
)
content = content.replace(anchor1, new1)

# 2. Add the helper function that reads both CSVs, right after
#    DATES_HTML_PATH's own constant block ends -- find a stable,
#    unique anchor: the load_config function definition, which is
#    guaranteed to exist and come after the path constants.
anchor2 = "def load_config():"
assert content.count(anchor2) == 1, f"anchor2 matches: {content.count(anchor2)}"
new2 = (
    'def get_recorded_dates():\n'
    '    """Read both no-shootout and partial-shootout CSVs, tag each\n'
    '    entry with its type, and return combined, sorted newest-first."""\n'
    '    entries = []\n'
    '    for csv_path, date_type in (\n'
    '        (NO_SHOOTOUT_CSV, "none"),\n'
    '        (PARTIAL_SHOOTOUT_CSV, "single"),\n'
    '    ):\n'
    '        if not csv_path.exists():\n'
    '            continue\n'
    '        lines = csv_path.read_text().splitlines()[1:]  # skip header\n'
    '        for line in lines:\n'
    '            date_str = line.strip()\n'
    '            if date_str:\n'
    '                entries.append({"date": date_str, "type": date_type})\n'
    '    entries.sort(key=lambda e: e["date"], reverse=True)\n'
    '    return entries\n'
    '\n'
    '\n' + anchor2
)
content = content.replace(anchor2, new2)

path.write_text(content)
print("launcher_server.py updated successfully")
