#!/usr/bin/env python3
"""
patch_remove_stale_shuffle_note.py

One-time patch: two wording fixes on the Shootout 2 Shuffle toggle.

1. Removes the "Not yet wired into automation" note entirely -- it's
   now stale. create_shootout.py's set_move_players() genuinely sets
   this field on Den at launch time as of the earlier patch today.

2. Removes "(Den default)" from the Two-up/Two-down label -- Two-up/
   Two-down isn't actually Den's factory default so much as it's just
   the setting SAM has historically used.

Run once from the launcher/ directory:
    python3 patch_remove_stale_shuffle_note.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "control_panel.html"

OLD_CSS = '  .shuffle-note { font-size: 11px; color: #f0b429; margin-bottom: 10px; line-height: 1.4; }\n'
NEW_CSS = ''

OLD_NOTE = '    <div class="shuffle-note">Not yet wired into automation — saved here for reference, but create_shootout.py does not currently set this field on Den; Den\'s own existing setting is left untouched at launch time.</div>\n'
NEW_NOTE = ''

OLD_LABEL = 'Two-up / Two-down (Den default)'
NEW_LABEL = 'Two-up / Two-down'


def main():
    text = TARGET.read_text(encoding="utf-8")

    for old, new, label in [
        (OLD_CSS, NEW_CSS, "shuffle-note CSS rule"),
        (OLD_NOTE, NEW_NOTE, "stale warning div"),
        (OLD_LABEL, NEW_LABEL, "Den default label"),
    ]:
        count = text.count(old)
        if count != 1:
            print(f"✗ Aborting: expected exactly 1 match for {label}, found {count}. "
                  f"File may have already been patched, or changed unexpectedly.")
            return 1
        text = text.replace(old, new)

    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — removed stale not-yet-wired note and "
          f"inaccurate Den default label.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
