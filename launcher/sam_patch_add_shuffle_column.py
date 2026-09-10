#!/usr/bin/env python3
"""
patch_add_shuffle_column.py

One-time patch: the underlying data (shootout2_shuffle_mode) has been
recorded in launch_log.jsonl since earlier today, but the visible
Launch Log table in the control panel never got a matching column.
Adds one. Older entries that predate this logging show "—" rather than
blank/undefined.

Run once from the launcher/ directory:
    python3 patch_add_shuffle_column.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "control_panel.html"

OLD_HEADER = '      <tr><th>Timestamp (MST)</th><th>Status</th><th>Seeding Basis</th><th>Players Removed Prior to Launch</th></tr>'
NEW_HEADER = '      <tr><th>Timestamp (MST)</th><th>Status</th><th>Seeding Basis</th><th>Shuffle</th><th>Players Removed Prior to Launch</th></tr>'

OLD_ROW = '''    return `<tr>
      <td>${e.timestamp}</td>
      <td><span class="badge ${badgeClass}">${e.status}</span></td>
      <td>${e.seeding_basis || '—'}</td>
      <td>${removed}</td>
    </tr>`;'''

NEW_ROW = '''    return `<tr>
      <td>${e.timestamp}</td>
      <td><span class="badge ${badgeClass}">${e.status}</span></td>
      <td>${e.seeding_basis || '—'}</td>
      <td>${e.shootout2_shuffle_mode || '—'}</td>
      <td>${removed}</td>
    </tr>`;'''

OLD_EMPTY = "    body.innerHTML = '<tr><td colspan=\"4\">No launches logged yet.</td></tr>';"
NEW_EMPTY = "    body.innerHTML = '<tr><td colspan=\"5\">No launches logged yet.</td></tr>';"


def main():
    text = TARGET.read_text(encoding="utf-8")

    for old, new, label in [
        (OLD_HEADER, NEW_HEADER, "table header"),
        (OLD_ROW, NEW_ROW, "row rendering"),
        (OLD_EMPTY, NEW_EMPTY, "empty-state colspan"),
    ]:
        count = text.count(old)
        if count != 1:
            print(f"✗ Aborting: expected exactly 1 match for {label}, found {count}. "
                  f"File may have already been patched, or changed unexpectedly.")
            return 1
        text = text.replace(old, new)

    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — Launch Log table now shows a Shuffle column.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
