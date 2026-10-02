#!/usr/bin/env python3
"""
Patch: get_recorded_tryout_names() now returns only the 10 most recent
entries, requested so the Identify Tryout Player page's log doesn't grow
unbounded.

Run once from the repo root: python3 sam_cap_tryout_names_log.py
Safe to re-run: asserts the anchor matches exactly once.
"""
from pathlib import Path

path = Path("launcher/launcher_server.py")
content = path.read_text()

old = (
    '            date_str, real_name = line.split(",", 1)\n'
    '            entries.append({"date": date_str.strip(), "real_name": real_name.strip()})\n'
    '    entries.sort(key=lambda e: e["date"], reverse=True)\n'
    '    return entries\n'
)
new = (
    '            date_str, real_name = line.split(",", 1)\n'
    '            entries.append({"date": date_str.strip(), "real_name": real_name.strip()})\n'
    '    entries.sort(key=lambda e: e["date"], reverse=True)\n'
    '    return entries[:10]  # most recent 10 only -- requested so this log stays short\n'
)

n = content.count(old)
assert n == 1, f"anchor: expected exactly 1 match, found {n}"
content = content.replace(old, new)

path.write_text(content)
print("launcher_server.py updated successfully")
