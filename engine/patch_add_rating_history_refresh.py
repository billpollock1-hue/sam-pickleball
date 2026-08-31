#!/usr/bin/env python3
"""
patch_add_rating_history_refresh.py

One-time patch: adds a manual Refresh button, a persistent freshness hint,
and the fresh-on-load / periodic-recheck cache-busting system to
build_rating_history_html() in pickleball_engine_v2.py -- same freshness
system already added to court assignments, signup viewer, session viewer,
and leaderboard.

This page has no dropdown/date-select state to preserve across a reload
(it's a single Plotly chart with Time Range/Quartile buttons, not a
per-date viewer), so its forceRefresh() is the simpler no-state-preserved
version already used on the leaderboard page.

Run once from the engine/ directory:
    python3 patch_add_rating_history_refresh.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "pickleball_engine_v2.py"

OLD_MENU_BLOCK = '''  <a href="index.html" style="position:fixed;top:10px;left:10px;z-index:1000;background:#1F4E79;color:#fff;font-size:12px;padding:6px 12px;border-radius:6px;text-decoration:none;box-shadow:0 1px 4px rgba(0,0,0,0.2);">&larr; Menu</a>
  <div id="sidebar">'''

NEW_MENU_BLOCK = '''  <a href="index.html" style="position:fixed;top:10px;left:10px;z-index:1000;background:#1F4E79;color:#fff;font-size:12px;padding:6px 12px;border-radius:6px;text-decoration:none;box-shadow:0 1px 4px rgba(0,0,0,0.2);">&larr; Menu</a>
  <button onclick="forceRefresh()" style="position:fixed;top:10px;left:96px;z-index:1000;background:#1F4E79;color:#fff;font-size:12px;padding:6px 12px;border-radius:6px;border:none;cursor:pointer;box-shadow:0 1px 4px rgba(0,0,0,0.2);">&#8635;&nbsp;Refresh</button>
  <div id="freshness-hint" style="position:fixed;top:42px;left:10px;z-index:999;font-size:10px;color:#888;background:#fff;padding:2px 6px;border-radius:4px;box-shadow:0 1px 3px rgba(0,0,0,0.15);">\N{ELECTRIC LIGHT BULB} Tap Refresh for the latest data.</div>
  <div id="sidebar">'''

OLD_SCRIPT_START = '''  <script>
    var chartDiv = document.getElementById('ratingChart');'''

NEW_SCRIPT_START = '''  <script>
    // Freshness: force a genuine network fetch on every real navigation to
    // this page, bypassing any browser/CDN cache. If this load doesn't
    // already carry our cache-bust marker, immediately redirect to a URL
    // that does -- GitHub Pages' CDN (and browsers) cache by full URL
    // including query string, so a unique timestamp guarantees a cache miss.
    (function () {{
      var params = new URLSearchParams(location.search);
      if (!params.has('_cb')) {{
        params.set('_cb', Date.now());
        location.replace(location.pathname + '?' + params.toString());
      }}
    }})();

    // Forces a genuine network fetch bypassing any cache -- used both by
    // the manual Refresh button and the periodic timer below. No state to
    // preserve on this page (Time Range / Quartile selections are just
    // client-side filters on data already embedded in the page, not a
    // per-date server-driven view).
    function forceRefresh() {{
      var params = new URLSearchParams(location.search);
      params.set('_cb', Date.now());
      location.replace(location.pathname + '?' + params.toString());
    }}
    setInterval(forceRefresh, 5 * 60 * 1000);

    var chartDiv = document.getElementById('ratingChart');'''


def main():
    text = TARGET.read_text(encoding="utf-8")

    for old, new, label in [
        (OLD_MENU_BLOCK, NEW_MENU_BLOCK, "menu block"),
        (OLD_SCRIPT_START, NEW_SCRIPT_START, "script start"),
    ]:
        count = text.count(old)
        if count != 1:
            print(f"✗ Aborting: expected exactly 1 match for {label}, found {count}. "
                  f"File may have already been patched, or changed unexpectedly.")
            return 1
        text = text.replace(old, new)

    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — added Refresh button, freshness hint, and "
          f"cache-busting system to build_rating_history_html().")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
