#!/usr/bin/env python3
"""
patch_fix_move_players_selector.py

One-time patch: fixes the Move Players field selector, which failed on
first live test (2026-08-21). Root cause confirmed from the debug log:
the old selector -- "next div OR vaadin-select" -- matched a hidden,
unrelated <div slot="error-message" id="error-message-vaadin-select-129">
sitting near the real field, since a plain div matched before reaching
the actual vaadin-select element. Narrowed to match ONLY a vaadin-select
element, skipping any divs in between entirely.

Run once from the assignments/ directory:
    python3 patch_fix_move_players_selector.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "create_shootout.py"

OLD_LINE = '            "xpath=following::*[self::vaadin-select or self::div][1]"'
NEW_LINE = '            "xpath=following::vaadin-select[1]"'


def main():
    text = TARGET.read_text(encoding="utf-8")
    count = text.count(OLD_LINE)
    if count != 1:
        print(f"✗ Aborting: expected exactly 1 match, found {count}. "
              f"File may have already been patched, or changed unexpectedly.")
        return 1
    text = text.replace(OLD_LINE, NEW_LINE)
    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — Move Players selector now matches only "
          f"a vaadin-select element, skipping the hidden error-message div.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
