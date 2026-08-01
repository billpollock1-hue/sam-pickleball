#!/usr/bin/env python3
"""
patch_fmt_ts_ampm.py

One-time patch: fmt_ts() previously showed times like "7/22 11:38" using
24-hour hour values with no AM/PM label -- technically unambiguous (11 in
24-hour notation is always AM; PM hours would show as 13-23), but not
obvious at a glance without already knowing the system's convention.
Confirmed live: a real "11:38" entry needed a tooltip hover to confirm it
was actually 11:38 AM. Switches to explicit 12-hour + AM/PM so every
timestamp is self-explanatory without hovering.

Run once from the signup-monitor/ directory:
    python3 patch_fmt_ts_ampm.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "generate_signup_viewer.py"

OLD_FMT_TS = '''def fmt_ts(ts: str) -> str:
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        return f"{dt.month}/{dt.day} {dt.hour}:{dt.minute:02d}"
    except Exception:
        return ts'''

NEW_FMT_TS = '''def fmt_ts(ts: str) -> str:
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        hour12 = dt.hour % 12
        if hour12 == 0:
            hour12 = 12
        ampm = "AM" if dt.hour < 12 else "PM"
        return f"{dt.month}/{dt.day} {hour12}:{dt.minute:02d} {ampm}"
    except Exception:
        return ts'''


def main():
    text = TARGET.read_text(encoding="utf-8")
    count = text.count(OLD_FMT_TS)
    if count != 1:
        print(f"✗ Aborting: expected exactly 1 match for fmt_ts(), found {count}. "
              f"File may have already been patched, or changed unexpectedly.")
        return 1
    text = text.replace(OLD_FMT_TS, NEW_FMT_TS)
    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — fmt_ts() now shows explicit AM/PM.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
