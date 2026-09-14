#!/usr/bin/env python3
"""
One-off patch: two related fixes for diagnosing/preventing the
intermittent Den page-timeout failures seen on several mornings
(8/24, 8/26, 8/27, 9/2, 9/3 -- always transient, always recovered by
the poller's automatic 5-min retry, but never actually explained).

1. Search-button selector case-sensitivity risk: the code used
   get_by_role("button", name="Search", exact=True) -- an exact,
   case-sensitive match. A post-failure screenshot from 2026-09-03
   showed the button rendered as "SEARCH" (all-caps) on a fully
   loaded page at the moment of failure. If the button's computed
   accessible name is ever "SEARCH" rather than "Search" (e.g. due to
   CSS text-transform being included in accessible-name computation,
   or a timing race while the page is still finishing rendering),
   this selector could never match it even while visibly present.
   Switched to a case-insensitive, whole-string regex match --
   removes this specific risk without loosening to a substring match
   that could accidentally hit an unrelated element.

2. Trace-on-failure: previously the only diagnostic evidence on any
   failure was a single _debug_screenshot() taken AFTER the exception
   was already caught -- which can look completely normal even when
   it wasn't at the actual moment of timeout (exactly what happened
   2026-09-03: the post-failure screenshot showed a fully-loaded,
   working page). Playwright's tracing captures the actual timeline
   -- DOM snapshots, network activity, console messages -- across the
   whole run, viewable afterward in Playwright's trace viewer
   (https://trace.playwright.dev). Only written to disk on failure
   (discarded on success) to avoid clutter.

Run once from the repo root: python3 sam_fix_search_selector_and_add_tracing.py
Safe to re-run: asserts each anchor matches exactly once.
"""
from pathlib import Path

path = Path("assignments/create_shootout_rating_seeded.py")
content = path.read_text()

# 1. Case-insensitive, whole-string Search button match.
anchor1 = 'search_button = page.get_by_role("button", name="Search", exact=True)'
assert content.count(anchor1) == 1, f"anchor1 matches: {content.count(anchor1)}"
new1 = (
    'search_button = page.get_by_role(\n'
    '            "button", name=re.compile(r"^Search$", re.IGNORECASE)\n'
    '        )'
)
content = content.replace(anchor1, new1)

# 2. Start tracing right after the context is created (covers the
#    whole run, both context-creation branches).
anchor2 = (
    '        if Path(SESSION_FILE).exists():\n'
    '            context = browser.new_context(storage_state=SESSION_FILE, viewport=VIEWPORT)\n'
    '        else:\n'
    '            context = browser.new_context(viewport=VIEWPORT)\n'
    '\n'
    '        page = context.new_page()'
)
assert content.count(anchor2) == 1, f"anchor2 matches: {content.count(anchor2)}"
new2 = (
    '        if Path(SESSION_FILE).exists():\n'
    '            context = browser.new_context(storage_state=SESSION_FILE, viewport=VIEWPORT)\n'
    '        else:\n'
    '            context = browser.new_context(viewport=VIEWPORT)\n'
    '\n'
    '        # Trace the whole run for real diagnostic evidence on failure --\n'
    '        # a post-failure screenshot only shows how the page looked AFTER\n'
    '        # the exception was already caught, which can look completely\n'
    '        # normal even when it wasn\'t at the actual moment of timeout.\n'
    '        # Only saved to disk on failure (see except block below);\n'
    '        # discarded on success to avoid clutter.\n'
    '        context.tracing.start(screenshots=True, snapshots=True, sources=True)\n'
    '\n'
    '        page = context.new_page()'
)
content = content.replace(anchor2, new2)

# 2b. Initialize the stop-tracking flag alongside the other pre-try
#     variables, so it exists even if something fails before the
#     except block would otherwise set it.
anchor2b = (
    '        excess_names = []\n'
    '        court_assignments_log = []\n'
    '        actual_shuffle_mode = None\n'
    '        try:'
)
assert content.count(anchor2b) == 1, f"anchor2b matches: {content.count(anchor2b)}"
new2b = (
    '        excess_names = []\n'
    '        court_assignments_log = []\n'
    '        actual_shuffle_mode = None\n'
    '        trace_already_stopped = False\n'
    '        try:'
)
content = content.replace(anchor2b, new2b)

# 3. Save the trace on failure, right alongside the existing screenshot.
#    Track whether we already stopped tracing here, so the `finally`
#    block below doesn't try to stop it a second time (which errors).
anchor3 = (
    '            _debug_screenshot(page, "fatal_failure")\n'
    '            raise'
)
assert content.count(anchor3) == 1, f"anchor3 matches: {content.count(anchor3)}"
new3 = (
    '            _debug_screenshot(page, "fatal_failure")\n'
    '            try:\n'
    '                ts = datetime.now().strftime("%Y%m%d_%H%M%S")\n'
    '                trace_path = DEBUG_DIR / f"fatal_failure_trace_{ts}.zip"\n'
    '                context.tracing.stop(path=str(trace_path))\n'
    '                trace_already_stopped = True\n'
    '                print(f"  (trace saved: {trace_path} -- view with "\n'
    '                      f"\'npx playwright show-trace {trace_path}\' "\n'
    '                      f"or by dragging it onto https://trace.playwright.dev)")\n'
    '            except Exception:\n'
    '                pass\n'
    '            raise'
)
content = content.replace(anchor3, new3)

# 4. On success (or if the except block's own tracing.stop() above
#    failed for some unrelated reason), discard the trace. Guarded by
#    trace_already_stopped so we never call tracing.stop() twice.
anchor4 = '        finally:\n            browser.close()'
assert content.count(anchor4) == 1, f"anchor4 matches: {content.count(anchor4)}"
new4 = (
    '        finally:\n'
    '            if not trace_already_stopped:\n'
    '                try:\n'
    '                    context.tracing.stop()  # no path = discard\n'
    '                except Exception:\n'
    '                    pass\n'
    '            browser.close()'
)
content = content.replace(anchor4, new4)

path.write_text(content)
print("create_shootout_rating_seeded.py updated successfully")
