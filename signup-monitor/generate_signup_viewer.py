"""
Generate a self-contained HTML signup viewer with date dropdown and print-to-PDF.
Embeds all log data as JSON — works without a web server.

Usage:
  python3 generate_signup_viewer.py    # generates logs/signup_viewer.html
"""

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).parent
LOGS_DIR = BASE_DIR / "logs"
OUTPUT = LOGS_DIR / "signup_viewer.html"

# Absolute path to the real git repo, NOT derived from BASE_DIR.parent --
# this script runs from two different locations (the git-tracked
# signup-monitor/ source, and the deployed PBMonitor copy that the
# automated 15-min launchd job actually uses). BASE_DIR.parent/"docs"
# only ever resolved correctly from the git-tracked location; from
# PBMonitor it silently resolved to a nonexistent "Application
# Support/docs" folder, crashing with FileNotFoundError -- meaning the
# automated sync to the live site had likely never actually worked.
DOCS_OUTPUT = Path(
    "/Users/billpollock/Documents/SAM Pickleball/sam-pickleball/docs/signup_viewer.html"
)


def canonical(name: str) -> str:
    return name.replace(" (Wait List)", "").strip()


def is_wl(name: str) -> bool:
    return "(Wait List)" in name


def fmt_ts(ts: str) -> str:
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        return f"{dt.month}/{dt.day} {dt.hour}:{dt.minute:02d}"
    except Exception:
        return ts


def fmt_date(ts: str) -> str:
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        return f"{dt.month}/{dt.day}"
    except Exception:
        return ts


def fmt_full_ts(ts: str) -> str:
    """Full, unambiguous timestamp for tooltips -- e.g. "July 9, 2026, 9:15 PM MST".
    All timestamps in these logs are recorded in true Phoenix/MST (see the
    monitor_signups.py fix -- previously mislabeled as generic "MT" using
    America/Denver, which silently drifted an hour during DST months)."""
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%B %-d, %Y, %-I:%M %p") + " MST"
    except Exception:
        return ts


def parse_log(date_str: str) -> Optional[dict]:
    log_file = LOGS_DIR / f"{date_str}_signup_log.csv"
    if not log_file.exists():
        return None

    # ── Read raw events ───────────────────────────────────────────────────────
    raw = []
    with log_file.open(newline="") as f:
        for row in csv.reader(f):
            if not row or row[0].startswith("#") or row[0] == "timestamp_mt":
                continue
            if len(row) < 4:
                continue
            ts, action, name = row[0], row[1], row[2]
            try:
                order = int(row[3])
            except (ValueError, IndexError):
                continue
            raw.append({"ts": ts, "action": action, "name": name, "order": order})

    # ── Detect WL → regular transitions ──────────────────────────────────────
    # A transition is when "withdrew X (Wait List)" and "joined X" both appear
    # at the same timestamp — the player moved off the wait list.
    by_ts = {}
    for e in raw:
        by_ts.setdefault(e["ts"], []).append(e)

    transitions = set()          # (ts, canonical) pairs
    pending_by_ts = {}           # ts → {canonical: new_regular_order}
    for ts, events in by_ts.items():
        wd_wl  = {canonical(e["name"]) for e in events
                  if e["action"] == "withdrew" and is_wl(e["name"])}
        jn_reg = {canonical(e["name"]): e["order"] for e in events
                  if e["action"] in ("joined*", "joined") and not is_wl(e["name"])}
        for c in wd_wl & set(jn_reg):
            transitions.add((ts, c))
            pending_by_ts.setdefault(ts, {})[c] = jn_reg[c]

    # ── Build revision columns ───────────────────────────────────────────────
    # A column is needed for any timestamp with a real withdrawal, a
    # WL→regular promotion, or a WL departure — a "pure promotion" (someone
    # backfilled from the wait list with no accompanying withdrawal at that
    # exact instant, e.g. added court capacity) still needs its own column,
    # or that seat change never shows up anywhere in the table.
    real_withdrawal_ts = {
        e["ts"] for e in raw
        if e["action"] in ("withdrew", "removed_auto") and (e["ts"], canonical(e["name"])) not in transitions
    }
    wl_departure_ts = {
        e["ts"] for e in raw if e["action"] in ("withdrew", "removed_auto") and is_wl(e["name"])
    }
    revision_ts = sorted(real_withdrawal_ts | set(pending_by_ts.keys()) | wl_departure_ts)

    rev_by_ts = {}
    revisions = []
    for ts in revision_ts:
        rev = {"ts": ts, "withdrawals": [], "withdrawal_action": {}, "reorders": {},
               "transitions": pending_by_ts.get(ts, {}), "header": ""}
        rev_by_ts[ts] = rev
        revisions.append(rev)

    # ── Replay chronologically: build player rows + a live wait-list queue ───
    # WL rank is NOT a fixed formula off one static threshold — court
    # capacity itself can grow over time (e.g. a court gets added), which
    # promotes a whole block of wait-listed players without any specific
    # withdrawal freeing their exact seat. So instead we track who is
    # *actually* on the wait list right now (active_wl, in queue order) and
    # derive each player's WLx label from their live position in it.
    players = []
    player_map = {}
    active_wl = []            # canonical names currently wait-listed, in order
    last_shown_wl_rank = {}   # canonical -> last WL rank rendered in the table

    for ts in sorted(by_ts.keys()):
        for e in by_ts[ts]:
            action, name, order = e["action"], e["name"], e["order"]
            c = canonical(name)

            if action in ("joined*", "joined"):
                # Skip the "regular" half of a WL→regular transition — the
                # row already exists from their original WL join.
                if (ts, c) in transitions and not is_wl(name):
                    continue

                if c not in player_map:
                    if is_wl(name):
                        active_wl.append(c)
                        rank = len(active_wl)
                        last_shown_wl_rank[c] = rank
                        initial = f"WL{rank}"
                    else:
                        initial = f"{order}{'*' if action == 'joined*' else ''}"
                    p = {"name": c, "joined": fmt_ts(ts), "initial": initial,
                         "withdrew": False, "revs": []}
                    player_map[c] = p
                    players.append(p)
                elif not is_wl(name):
                    # Withdrew and rejoined — add a second row. Reassign
                    # player_map[c] (not a separate suffixed key) so every
                    # later event for this name -- withdrawals, reorders --
                    # resolves to this new, currently-open episode instead
                    # of silently continuing to mutate the stale original
                    # row. Previously this used a "c + '†'" key here, which
                    # left player_map[c] pointing at the closed original
                    # row forever; any subsequent withdrawal/reorder for
                    # this name (e.g. Greg Egli's and Tron Brinkmann's
                    # 7/21 18:12 withdrawal after rejoining at 17:57) was
                    # then wrongly applied to that stale original row
                    # instead of the real, currently-active rejoined row.
                    # Because a rejoin can only happen after a withdrawal,
                    # the plain name key always naturally tracks whichever
                    # episode is currently open, even across multiple
                    # rejoin cycles for the same person.
                    p = {"name": c + " (rejoined)", "joined": fmt_ts(ts),
                         "initial": str(order), "withdrew": False, "revs": []}
                    player_map[c] = p
                    players.append(p)

            elif action in ("withdrew", "removed_auto"):
                if is_wl(name):
                    if c in active_wl:
                        active_wl.remove(c)
                    last_shown_wl_rank.pop(c, None)
                    if (ts, c) not in transitions:
                        # A real WL departure, not a promotion elsewhere.
                        rev = rev_by_ts.get(ts)
                        if rev is not None:
                            rev["withdrawals"].append(c)
                            rev["withdrawal_action"][c] = action
                        if c in player_map:
                            player_map[c]["withdrew"] = True
                else:
                    rev = rev_by_ts.get(ts)
                    if rev is not None:
                        rev["withdrawals"].append(c)
                        rev["withdrawal_action"][c] = action
                    if c in player_map:
                        player_map[c]["withdrew"] = True

            elif action == "reordered":
                # Regular-seat reorders use the logged order value directly.
                # WL-queue reorders are derived below from active_wl's live
                # state instead of trusting the log's (possibly stale, since
                # capacity can shift) number.
                if c not in active_wl:
                    rev = rev_by_ts.get(ts)
                    if rev is not None:
                        rev["reorders"][c] = order

        # After this timestamp's events, record any resulting shift in the
        # live wait-list queue (removals shift everyone behind them up).
        rev = rev_by_ts.get(ts)
        if rev is not None:
            for idx, c in enumerate(active_wl):
                rank = idx + 1
                if last_shown_wl_rank.get(c) != rank:
                    rev["reorders"][c] = ("wl", rank)
                    last_shown_wl_rank[c] = rank

    for rev in revisions:
        if rev["withdrawals"]:
            names = [w.split()[0] for w in rev["withdrawals"]]
            if len(names) == 1:
                header_names = names[0]
            elif len(names) == 2:
                header_names = " & ".join(names)
            else:
                header_names = f"{names[0]} +{len(names) - 1}"
            all_auto = all(rev["withdrawal_action"].get(w) == "removed_auto" for w in rev["withdrawals"])
            verb = "auto-removed" if all_auto else "wd"
            rev["header"] = f"After {header_names}\n{verb} {fmt_ts(rev['ts'])}"
        else:
            # Pure promotion — nobody left the sheet at this instant, earlier
            # withdrawals just got backfilled from the wait list.
            promoted = [p.split()[0] for p in rev["transitions"].keys()]
            if len(promoted) == 1:
                promo_names = promoted[0]
            elif len(promoted) == 2:
                promo_names = " & ".join(promoted)
            else:
                promo_names = f"{promoted[0]} +{len(promoted) - 1}"
            rev["header"] = f"{promo_names} promoted\n{fmt_date(rev['ts'])}"

    # ── Populate revision cells on each player row ────────────────────────────
    n = len(revisions)
    for p in players:
        p["revs"] = [None] * n

    for ri, rev in enumerate(revisions):
        # Each withdrawn player's own cell -- WD (red) for a real player
        # withdrawal, AUTO (amber) for a shootout-launcher court-count
        # trim, so the two very different situations aren't visually
        # conflated with each other.
        for wd_c in rev["withdrawals"]:
            if wd_c in player_map:
                if rev["withdrawal_action"].get(wd_c) == "removed_auto":
                    player_map[wd_c]["revs"][ri] = {"t": "auto", "v": f"AUTO {fmt_ts(rev['ts'])}", "title": fmt_full_ts(rev['ts']) + " — removed by shootout launcher (court-count trim)"}
                else:
                    player_map[wd_c]["revs"][ri] = {"t": "wd", "v": f"WD {fmt_ts(rev['ts'])}", "title": fmt_full_ts(rev['ts'])}

        # Players who reordered due to this withdrawal (regular seat number,
        # or a live-tracked WL queue-position shift)
        for c, val in rev["reorders"].items():
            if c not in player_map:
                continue
            if isinstance(val, tuple) and val[0] == "wl":
                player_map[c]["revs"][ri] = {"t": "rev", "v": f"WL{val[1]}"}
            else:
                player_map[c]["revs"][ri] = {"t": "rev", "v": str(val)}

        # Players promoted from WL to regular by this withdrawal — always a
        # real court seat, never re-labeled as WL regardless of position.
        for c, new_order in rev["transitions"].items():
            if c in player_map:
                player_map[c]["revs"][ri] = {"t": "promoted", "v": str(new_order)}

    return {
        "cols": [{"h": r["header"]} for r in revisions],
        "rows": [
            {
                "n": p["name"],
                "j": p["joined"],
                "o": p["initial"],
                "w": p["withdrew"],
                "r": p["revs"],
            }
            for p in players
        ],
    }


# ── HTML template ─────────────────────────────────────────────────────────────

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SAM 6AM Shootout — Signup Viewer</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       font-size: 13px; color: #222; background: #f4f4f4; }

/* ── Controls bar ── */
#controls { display: flex; align-items: center; gap: 12px; padding: 12px 20px;
            background: #fff; border-bottom: 1px solid #ddd;
            position: sticky; top: 0; z-index: 10; }
#controls label { font-size: 12px; color: #666; }
#date-select { font-size: 13px; padding: 5px 8px; border: 1px solid #ccc;
               border-radius: 5px; background: #fff; cursor: pointer; }
#print-btn { margin-left: auto; padding: 6px 16px; font-size: 12px;
             border: 1px solid #bbb; border-radius: 5px; background: #fff;
             cursor: pointer; white-space: nowrap; }
#print-btn:hover { background: #f0f0f0; }

.back-btn { padding: 6px 14px; font-size: 12px; border: none;
            border-radius: 5px; background: #1F4E79; color: #fff;
            cursor: pointer; text-decoration: none; white-space: nowrap; }
.back-btn:hover { background: #163a5c; }
#freshness-hint { padding: 6px 20px; font-size: 11px; color: #888;
                   background: #fafafa; border-bottom: 1px solid #eee; }

/* ── Content area ── */
#content { padding: 20px; overflow-x: auto; }
#print-header { display: none; font-size: 14px; font-weight: 600;
                margin-bottom: 12px; }

/* ── Table ── */
table { border-collapse: collapse; font-size: 12px; }
th { background: #ebebeb; color: #555; font-weight: 600; padding: 6px 10px;
     border: 1px solid #ddd; white-space: pre-line; line-height: 1.35;
     text-align: center; }
th.left { text-align: left; }
td { padding: 5px 9px; border: 1px solid #e4e4e4; vertical-align: middle; }

td.ts     { color: #aaa; font-size: 11px; font-family: monospace;
            text-align: center; white-space: nowrap; }
td.name   { white-space: nowrap; }
td.order  { text-align: center; }
td.empty  { background: #fafafa; }
td.rev    { text-align: center; color: #444; }
td.wl     { text-align: center; color: #1565c0; font-weight: 500; }
td.promo  { text-align: center; color: #2e7d32; font-weight: 500; }
td.wd-cell { text-align: center; background: #fff0f0;
             color: #c0392b; font-weight: 600; font-size: 11px; }
td.auto-cell { text-align: center; background: #fff6e0;
               color: #8a6d1f; font-weight: 600; font-size: 11px; }

tr.wd td       { color: #c8c8c8; }
tr.wd td.name  { text-decoration: line-through; }

#footnote { padding: 10px 0 0; font-size: 11px; color: #999; font-style: italic; }

/* ── Print ── */
@media print {
  body { background: #fff; }
  #controls { display: none; }
  #print-header { display: block; }
  #content { padding: 0; }
  table { font-size: 10px; }
  td, th { padding: 3px 7px; }
  @page { margin: 1.5cm; size: landscape; }
}
</style>
</head>
<body>

<div id="controls">
  <a href="index.html" class="back-btn">&larr; Menu</a>
  <button class="back-btn" onclick="forceRefresh()">&#8635;&nbsp;Refresh</button>
  <label for="date-select">Session date</label>
  <select id="date-select">%%OPTIONS%%</select>
  <button id="print-btn" onclick="window.print()">&#128438;&nbsp; Print / Save PDF</button>
</div>
<div id="freshness-hint">💡 Tap Refresh anytime to make sure you're seeing the latest data.</div>

<div id="content">
  <div id="print-header"></div>
  <div id="tbl"></div>
  <div id="footnote">* = present when sheet was first discovered</div>
</div>

<script>
// ── Freshness: force a genuine network fetch on every real navigation to
// this page, bypassing any browser/CDN cache. If this load doesn't already
// carry our cache-bust marker, immediately redirect to a URL that does --
// GitHub Pages' CDN (and browsers) cache by full URL including query
// string, so a unique timestamp guarantees a cache miss.
(function () {
  const params = new URLSearchParams(location.search);
  if (!params.has('_cb')) {
    params.set('_cb', Date.now());
    location.replace(location.pathname + '?' + params.toString());
  }
})();

const DATA = %%JSON%%;
const DATES = %%DATES%%;

function isWL(v) { return typeof v === 'string' && v.startsWith('WL'); }

function render(dateStr) {
  const d = DATA[dateStr];
  if (!d) return;

  // Print header
  const dt = new Date(dateStr + 'T12:00:00');
  document.getElementById('print-header').textContent =
    dt.toLocaleDateString('en-US', {weekday:'long', year:'numeric',
      month:'long', day:'numeric'}) + ' — SAM 6AM Shootout';

  const cols = d.cols || [];
  const rows = d.rows || [];

  let h = '<table><thead><tr>';
  h += '<th class="left" style="width:72px">Joined</th>';
  h += '<th class="left" style="min-width:160px">Player</th>';
  h += '<th style="width:44px">SU#</th>';
  for (const c of cols)
    h += `<th style="width:82px">${c.h}</th>`;
  h += '</tr></thead><tbody>';

  for (const p of rows) {
    h += `<tr${p.w ? ' class="wd"' : ''}>`;
    h += `<td class="ts">${p.j}</td>`;
    h += `<td class="name">${p.n}</td>`;
    h += `<td class="${isWL(p.o) ? 'wl' : 'order'}">${p.o}</td>`;
    for (const rev of p.r) {
      if (!rev) { h += '<td class="empty"></td>'; continue; }
      if (rev.t === 'wd')       { h += `<td class="wd-cell" title="${rev.title}">${rev.v}</td>`; continue; }
      if (rev.t === 'auto')     { h += `<td class="auto-cell" title="${rev.title}">${rev.v}</td>`; continue; }
      if (rev.t === 'promoted') { h += `<td class="promo">${rev.v}</td>`;   continue; }
      h += `<td class="${isWL(rev.v) ? 'wl' : 'rev'}">${rev.v}</td>`;
    }
    h += '</tr>';
  }

  h += '</tbody></table>';
  document.getElementById('tbl').innerHTML = h;
}

const sel = document.getElementById('date-select');

// Determine "today" and whether the 8:15 AM cutoff has passed, in Mountain
// Standard Time (MST — America/Phoenix, no DST, matches the run_all.sh scrape
// cutoff). Before 8:15 AM on a play date, that date's session hasn't been
// played yet, so it still counts as the next play date. After 8:15 AM,
// it's considered played and the default should roll forward to the next
// date that actually has a signup sheet.
function arizonaNow() {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Phoenix',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false
  }).formatToParts(new Date());
  const map = {};
  parts.forEach(p => { map[p.type] = p.value; });
  return {
    dateStr: `${map.year}-${map.month}-${map.day}`,
    hour: parseInt(map.hour, 10),
    minute: parseInt(map.minute, 10)
  };
}

const az = arizonaNow();
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
// Fallback: if all dates removed, restore the most recent past one
if (sel.options.length === 0 && DATES.length > 0) {
  const opt = document.createElement('option');
  opt.value = DATES[DATES.length - 1];
  opt.text = DATES[DATES.length - 1];
  sel.appendChild(opt);
}
// Ensure the first (nearest upcoming) date is the one actually selected —
// reordering options in the DOM does not change which one is marked selected.
sel.selectedIndex = 0;

// Restore a manually-selected date carried over from a periodic auto-reload
// (see setInterval below), if that date still appears in the dropdown --
// otherwise the reload would silently snap back to the default date while
// someone is actively reviewing an older session.
const preservedDate = new URLSearchParams(location.search).get('d');
if (preservedDate) {
  const match = Array.from(sel.options).find(o => o.value === preservedDate);
  if (match) sel.value = preservedDate;
}

sel.addEventListener('change', () => render(sel.value));
render(sel.value);

// Forces a genuine network fetch bypassing any cache, carrying the current
// date selection forward so it isn't lost -- used both by the manual
// Refresh button and the periodic timer below.
function forceRefresh() {
  const params = new URLSearchParams(location.search);
  params.set('_cb', Date.now());
  params.set('d', sel.value);
  location.replace(location.pathname + '?' + params.toString());
}

// Periodic freshness re-check for tabs left open a while.
setInterval(forceRefresh, 5 * 60 * 1000);
</script>
</body>
</html>
"""


def generate_viewer() -> Optional[Path]:
    all_data: dict = {}
    for log_file in sorted(LOGS_DIR.glob("*_signup_log.csv")):
        date_str = log_file.stem.replace("_signup_log", "")
        data = parse_log(date_str)
        if data:
            all_data[date_str] = data

    if not all_data:
        print("No log files found.")
        return None

    # Dropdown options — reverse chronological
    dates = sorted(all_data.keys(), reverse=True)
    options = []
    for d in dates:
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
            label = dt.strftime("%a, %b %-d, %Y")
        except Exception:
            label = d
        options.append(f'<option value="{d}">{label}</option>')

    html = (HTML_TEMPLATE
            .replace("%%OPTIONS%%", "\n    ".join(options))
            .replace("%%JSON%%", json.dumps(all_data, separators=(",", ":")))
            .replace("%%DATES%%", json.dumps(dates)))

    OUTPUT.write_text(html, encoding="utf-8")
    print(f"Saved: {OUTPUT}")

    # Fail soft: never let a missing/unreachable docs/ folder crash the
    # whole run (this previously took down monitor_signups.py's automated
    # regeneration step silently, every single cycle, since it runs from
    # a location where the old relative path never resolved correctly).
    try:
        DOCS_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        DOCS_OUTPUT.write_text(html, encoding="utf-8")
        print(f"Saved: {DOCS_OUTPUT}")
    except Exception as e:
        print(f"⚠ Could not write to {DOCS_OUTPUT}: {e}")

    return OUTPUT


if __name__ == "__main__":
    generate_viewer()
