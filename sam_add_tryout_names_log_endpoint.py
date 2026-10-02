#!/usr/bin/env python3
"""
Patch: adds a GET /api/recorded-tryout-names endpoint to launcher_server.py,
powering a new log section on the Identify Tryout Player admin page.
Reads data/tryout_name_fixes.csv (date,real_name) and returns it sorted
newest-first, same pattern as get_recorded_dates()/the dates.html log.

Run once from the repo root: python3 sam_add_tryout_names_log_endpoint.py
Safe to re-run: asserts each anchor matches exactly once.
"""
from pathlib import Path

path = Path("launcher/launcher_server.py")
content = path.read_text()


def replace_once(text, old, new, label):
    n = text.count(old)
    assert n == 1, f"{label}: expected exactly 1 match, found {n}"
    return text.replace(old, new)


# 1. Route, right after /api/record-date-status.
old1 = (
    '        elif self.path == "/api/record-date-status":\n'
    '            self._send_json(get_record_date_status())\n'
)
new1 = old1 + (
    '        elif self.path == "/api/recorded-tryout-names":\n'
    '            self._send_json(get_recorded_tryout_names())\n'
)
content = replace_once(content, old1, new1, "route")

# 2. Helper function, right before get_recorded_dates() so it sits with
#    the other "read a CSV, return sorted newest-first" helpers.
old2 = "def get_recorded_dates():"
new2 = (
    'def get_recorded_tryout_names():\n'
    '    """Read data/tryout_name_fixes.csv and return it sorted newest-first,\n'
    '    for the Identify Tryout Player page\'s log."""\n'
    '    entries = []\n'
    '    if TRYOUT_NAME_FIXES_CSV.exists():\n'
    '        lines = TRYOUT_NAME_FIXES_CSV.read_text().splitlines()[1:]  # skip header\n'
    '        for line in lines:\n'
    '            line = line.strip()\n'
    '            if not line:\n'
    '                continue\n'
    '            date_str, real_name = line.split(",", 1)\n'
    '            entries.append({"date": date_str.strip(), "real_name": real_name.strip()})\n'
    '    entries.sort(key=lambda e: e["date"], reverse=True)\n'
    '    return entries\n'
    '\n'
    '\n'
    'def get_recorded_dates():'
)
content = replace_once(content, old2, new2, "helper function")

path.write_text(content)
print("launcher_server.py updated successfully")
