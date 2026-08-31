#!/usr/bin/env python3
"""
patch_show_past_play_dates.py

One-time patch: the court assignments dropdown previously REMOVED every
date before today from the <select> entirely -- the underlying data for
past dates was always embedded in the page (Python side reads every file
in assignments_history/, not just future ones), but the JS filter hid
them. This patch stops removing anything; it only changes which date is
selected by DEFAULT (still the true next play date, same logic as
before), leaving the full history browsable -- same convention already
used by the Session Viewer.

Run once from the assignments/ directory:
    python3 patch_show_past_play_dates.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "generate_assignments_viewer.py"

OLD_BLOCK = '''const az = arizonaNow();
const cutoffPassed = (az.hour > 8) || (az.hour === 8 && az.minute >= 15);

// Filter dropdown to the true next play date and beyond, sorted nearest first
const allOpts = Array.from(sel.options);
allOpts.forEach(opt => {
  if (opt.value < az.dateStr) { opt.remove(); return; }
  if (opt.value === az.dateStr && cutoffPassed) { opt.remove(); return; }
});
// Reverse remaining options so nearest date is first
const remaining = Array.from(sel.options);
sel.innerHTML = '';
remaining.reverse().forEach(opt => sel.appendChild(opt));
// Fallback: if all dates removed, restore the last (most recent past) one
if (sel.options.length === 0 && DATES.length > 0) {
  const opt = document.createElement('option');
  opt.value = DATES[DATES.length - 1];
  opt.text = DATES[DATES.length - 1];
  sel.appendChild(opt);
}
// Ensure the first (nearest upcoming) date is the one actually selected —
// reordering options in the DOM does not change which one is marked selected.
sel.selectedIndex = 0;'''

NEW_BLOCK = '''const az = arizonaNow();
const cutoffPassed = (az.hour > 8) || (az.hour === 8 && az.minute >= 15);

// Determine the true "next play date" as the default selection, WITHOUT
// removing any dates from the dropdown -- full history stays browsable,
// same convention as the Session Viewer. DATES is sorted descending
// (newest first) server-side, so we sort a local ascending copy just for
// this lookup rather than relying on DATES' own order.
const ascendingDates = [...DATES].sort();
let defaultDate = ascendingDates.find(d => d > az.dateStr || (d === az.dateStr && !cutoffPassed));
if (!defaultDate) {
  // No future date on file (e.g. history hasn't caught up yet) -- fall
  // back to the most recent date available (DATES[0], since it's
  // descending).
  defaultDate = DATES[0];
}
if (defaultDate) {
  sel.value = defaultDate;
}'''


def main():
    text = TARGET.read_text(encoding="utf-8")
    count = text.count(OLD_BLOCK)
    if count != 1:
        print(f"✗ Aborting: expected exactly 1 match, found {count}. "
              f"File may have already been patched, or changed unexpectedly.")
        return 1
    text = text.replace(OLD_BLOCK, NEW_BLOCK)
    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — dropdown now shows full play-date history, "
          f"still defaulting to the next play date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
