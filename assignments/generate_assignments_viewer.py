"""
Generate a self-contained HTML court-assignments viewer with date dropdown
and DEN / Rating / Comparison tabs.

Reads JSON snapshots written by den_assignments.py (save_assignments_snapshot)
from output/assignments_history/ and embeds them all into one HTML file —
no server required.

Usage:
  python3 generate_assignments_viewer.py   # from the assignments/ directory
"""

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

OUT_DIR = Path("output")
HISTORY_DIR = OUT_DIR / "assignments_history"
OUTPUT = OUT_DIR / "court_assignments_viewer.html"

# Anchored to this script's own location, not the current working directory --
# run_all.sh invokes this via `(cd assignments && python3 generate_assignments_viewer.py)`,
# so a cwd-relative path would silently miss the repo-root data/ directory
# (the same bug already fixed in check_no_shootout.py).
NO_SHOOTOUT_LOG = Path(__file__).resolve().parent.parent / "data" / "no_shootout_dates.csv"


HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Anthem 6AM Shootout — Court Assignments</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       font-size: 13px; color: #222; background: #f4f4f4; }

/* ── Controls bar ── */
#controls { display: flex; align-items: center; gap: 12px; padding: 12px 20px;
            background: #fff; border-bottom: 1px solid #ddd;
            position: sticky; top: 0; z-index: 10; flex-wrap: wrap; }
#controls label { font-size: 12px; color: #666; }
#date-select { font-size: 13px; padding: 5px 8px; border: 1px solid #ccc;
               border-radius: 5px; background: #fff; cursor: pointer; }

#tabs { display: flex; gap: 4px; }
.tab-btn { padding: 6px 14px; font-size: 12px; border: 1px solid #ccc;
           border-radius: 5px; background: #fff; cursor: pointer; }
.tab-btn.active { background: #1565c0; color: #fff; border-color: #1565c0; }

.back-btn { padding: 6px 14px; font-size: 12px; border: none;
            border-radius: 5px; background: #1F4E79; color: #fff;
            cursor: pointer; text-decoration: none; white-space: nowrap; }
.back-btn:hover { background: #163a5c; }
#freshness-hint { padding: 6px 20px; font-size: 11px; color: #888;
                   background: #fafafa; border-bottom: 1px solid #eee; }

/* ── Content area ── */
#content { padding: 20px; max-width: 720px; }
.section { display: none; }
.section.active { display: block; }
.pg-header { margin-bottom: 14px; }
.pg-title { font-size: 15px; font-weight: 600; margin-bottom: 2px; }
.pg-sub { font-size: 12px; color: #666; }
.pg-warn { font-size: 12px; font-weight: bold; color: #c00000; margin-top: 3px; }
.pg-preliminary { font-size: 12px; font-weight: bold; color: #7030a0; margin-top: 3px; }

h2.court-title { font-size: 13px; font-weight: 700; color: #333;
                 margin: 18px 0 6px; padding-top: 10px; border-top: 2px solid #333; }
h2.court-title:first-child { border-top: none; padding-top: 0; margin-top: 0; }

table { border-collapse: collapse; table-layout: fixed; font-size: 12px; width: 100%; margin-bottom: 4px; }
th { background: #ebebeb; color: #555; font-weight: 600; padding: 5px 9px;
     border: 1px solid #ddd; text-align: left; overflow: hidden; text-overflow: ellipsis; }
th.num, td.num { text-align: right; }
td { padding: 4px 9px; border: 1px solid #e4e4e4; overflow-wrap: break-word; }

.wl-heading { font-size: 12px; font-weight: 700; color: #333; margin: 16px 0 6px;
              padding-top: 10px; border-top: 2px solid #333; }

.diff-row td { font-weight: 700; color: #c0392b; }

#comp-footer { margin-top: 10px; font-size: 12px; color: #555; font-weight: 600; }

/* ── Print (native browser print, e.g. Cmd+P / mobile share-sheet print) ── */
@media print {
  body { background: #fff; }
  #controls { display: none; }
  #content { padding: 0; max-width: none; }
  table { font-size: 11px; }
  td, th { padding: 4px 8px; }
  @page { size: letter portrait; margin: 0.75in 1in; }
}
</style>
</head>
<body>

<div id="controls">
  <a href="index.html" class="back-btn">&larr; Menu</a>
  <button class="back-btn" onclick="forceRefresh()">&#8635;&nbsp;Refresh</button>
  <label for="date-select">Session date</label>
  <select id="date-select"></select>

  <div id="tabs">
    <button class="tab-btn" data-tab="den">DEN</button>
    <button class="tab-btn" data-tab="rating">Rating</button>
    <button class="tab-btn" data-tab="comparison">Comparison</button>
  </div>
</div>
<div id="freshness-hint">💡 Tap Refresh anytime to make sure you're seeing the latest data.</div>

<div id="content">
  <div class="section" data-section="den"><div id="den-body"></div></div>
  <div class="section" data-section="rating"><div id="rating-body"></div></div>
  <div class="section" data-section="comparison"><div id="comparison-body"></div></div>
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
const NO_SHOOTOUT_DATES = new Set(%%NO_SHOOTOUT_DATES%%);
const MIN_PLAYERS_FOR_SHOOTOUT = 8;

function isWeekend(dateObj) {
  const day = dateObj.getDay(); // 0 = Sunday, 6 = Saturday
  return day === 0 || day === 6;
}

// Shared by isPreliminary() and the "RATINGS MAY BE STALE" check below --
// both need the same underlying fact: is there at least one calendar day,
// strictly between ratingsThroughStr and sessionDateStr, that was (or still
// could be) a real play day? A raw day-count gap isn't enough, since
// weekends and confirmed no-shootout days (logged in data/no_shootout_dates.csv)
// can make a multi-day gap contain zero actual opportunities for the
// ratings to have changed.
function hasRemainingPlayOpportunity(ratingsThroughDate, sessionDate) {
  const cursor = new Date(ratingsThroughDate);
  cursor.setDate(cursor.getDate() + 1);

  while (cursor < sessionDate) {
    const cursorStr = cursor.toISOString().slice(0, 10);
    if (!isWeekend(cursor) && !NO_SHOOTOUT_DATES.has(cursorStr)) {
      return true;
    }
    cursor.setDate(cursor.getDate() + 1);
  }

  return false;
}

function isPreliminary(dateStr, ratingsThrough) {
  if (!ratingsThrough) return false;
  const parts = ratingsThrough.split('/');
  if (parts.length !== 3) return false;
  const rDate = new Date('20' + parts[2] + '-' + parts[0].padStart(2,'0') + '-' + parts[1].padStart(2,'0') + 'T00:00:00');
  const sDate = new Date(dateStr + 'T00:00:00');

  // PRELIMINARY is only meaningful if at least one in-between day is a
  // genuine remaining play opportunity -- otherwise "will update as more
  // sessions are played before this date" is a promise that can't be kept.
  return hasRemainingPlayOpportunity(rDate, sDate);
}

function pageHeader(d, extra, dateStr) {
  let h = '<div class="pg-header">';
  h += `<div class="pg-title">ANTHEM 6 AM SHOOTOUT — ${d.date_display}</div>`;
  h += `<div class="pg-sub">${d.total_signups} Players • Generated ${d.generated}</div>`;
  if (extra) h += `<div class="pg-sub">${extra}</div>`;
  if (d.last_signup_change) {
    h += `<div class="pg-sub">Last signup change: ${d.last_signup_change} MST</div>`;
  }

  if (d.total_signups < MIN_PLAYERS_FOR_SHOOTOUT) {
    // Below DEN's minimum for a shootout to run at all -- this takes
    // priority over PRELIMINARY, since "assignments will update as more
    // sessions are played" is misleading when there's a real chance no
    // session happens on this date at all.
    h += `<div class="pg-warn">⚠ Only ${d.total_signups} players signed up — below the 8-player minimum for a shootout.</div>`;
  } else if (dateStr && isPreliminary(dateStr, d.ratings_through)) {
    h += `<div class="pg-preliminary">📋 PRELIMINARY — Court assignments and ratings will update as more sessions are played before this date.</div>`;
  } else {
    if (d.den_current === false) {
      h += `<div class="pg-warn">⚠ DEN ASSIGNMENTS STALE — Step/% data will refresh automatically at the next scheduled update.</div>`;
    }
    if (d.ratings_through) {
      const ratingsDate = new Date(d.ratings_through.replace(/(\d+)\/(\d+)\/(\d+)/, '20$3-$1-$2'));
      const sessionDate = dateStr ? new Date(dateStr + 'T00:00:00') : new Date();
      // Same day-walking rule as isPreliminary() -- a raw day-count gap
      // (the old "daysDiff > 1" check) fired even when the intervening
      // days were all weekends/confirmed no-shootout days and nothing
      // could actually have updated. See July 13, 2026 case: 7/10 ratings
      // vs a 7/14 session spans 4 calendar days but zero real play days
      // (7/11 Sat, 7/12 Sun, 7/13 confirmed no-shootout).
      if (hasRemainingPlayOpportunity(ratingsDate, sessionDate)) {
        h += `<div class="pg-warn">⚠ RATINGS MAY BE STALE — Based on results through ${d.ratings_through}. Updated ratings will appear automatically after the next scheduled refresh.</div>`;
      }
    }
  }


  h += '</div>';
  return h;
}

function courtColgroup(isRating) {
  return isRating
    ? '<colgroup><col style="width:16%"><col style="width:16%"><col style="width:40%"><col style="width:28%"></colgroup>'
    : '<colgroup><col style="width:14%"><col style="width:14%"><col style="width:38%"><col style="width:17%"><col style="width:17%"></colgroup>';
}

function fmtPct(pct) {
  return pct == null ? '' : `${pct.toFixed(1)}%`;
}

function courtTable(courtData, isRating) {
  const colgroup = courtColgroup(isRating);
  let h = '';
  for (const c of courtData.courts) {
    h += `<h2 class="court-title">COURT ${c.court}</h2>`;
    h += `<table>${colgroup}<thead><tr><th class="num">Pos</th><th class="num">SU</th><th>Player</th>`;
    h += isRating ? '<th class="num">Rating</th>' : '<th class="num">Step</th><th class="num">%</th>';
    h += '</tr></thead><tbody>';
    for (const p of c.players) {
      h += `<tr><td class="num">${p.pos}</td><td class="num">${p.su}</td><td>${p.name}</td>`;
      h += isRating
        ? `<td class="num">${p.rating ?? ''}</td>`
        : `<td class="num">${p.step ?? ''}</td><td class="num">${fmtPct(p.pct)}</td>`;
      h += '</tr>';
    }
    h += '</tbody></table>';
  }

  h += '<div class="wl-heading">WAIT LIST</div>';
  if (!courtData.waitlist.length) {
    h += '<p>None</p>';
  } else {
    h += `<table>${colgroup}<thead><tr><th class="num">Pos</th><th class="num">SU</th><th>Player</th>`;
    h += isRating ? '<th class="num">Rating</th>' : '<th class="num">Step</th><th class="num">%</th>';
    h += '</tr></thead><tbody>';
    for (const p of courtData.waitlist) {
      h += `<tr><td class="num">${p.pos}</td><td class="num">${p.su}</td><td>${p.name}</td>`;
      h += isRating
        ? `<td class="num">${p.rating ?? ''}</td>`
        : `<td class="num">${p.step ?? ''}</td><td class="num">${fmtPct(p.pct)}</td>`;
      h += '</tr>';
    }
    h += '</tbody></table>';
  }
  return h;
}

function moveLabel(diff) {
  if (diff === 0) return '';
  const n = Math.abs(diff);
  const courts = n === 1 ? 'court' : 'courts';
  return diff > 0 ? `Move up ${n} ${courts}` : `Move down ${n} ${courts}`;
}

function comparisonTable(comp) {
  const colgroup = '<colgroup><col style="width:28%"><col style="width:14%">'
    + '<col style="width:14%"><col style="width:44%"></colgroup>';
  let h = `<table>${colgroup}<thead><tr><th>Player</th><th class="num">DEN</th>`;
  h += '<th class="num">Model</th><th>Adjustment</th></tr></thead><tbody>';
  for (const r of comp.rows) {
    h += `<tr${r.diff !== 0 ? ' class="diff-row"' : ''}>`;
    h += `<td>${r.name}</td><td class="num">${r.den_court}</td>`;
    h += `<td class="num">${r.rating_court}</td><td>${moveLabel(r.diff)}</td></tr>`;
  }
  h += '</tbody></table>';
  h += `<div id="comp-footer">${comp.moved} of ${comp.total} players on different courts</div>`;
  return h;
}

function render(dateStr) {
  const d = DATA[dateStr];
  if (!d) return;

  const [yyyy, mm, dd] = dateStr.split('-');
  document.title = `${mm}-${dd}-${yyyy.slice(2)} SAM Court Assignments`;

  document.getElementById('den-body').innerHTML = pageHeader(d, null, dateStr) + courtTable(d.den, false);

  const hasRating = !!d.rating;
  document.querySelector('.tab-btn[data-tab="rating"]').style.display = hasRating ? '' : 'none';
  document.querySelector('.tab-btn[data-tab="comparison"]').style.display = hasRating ? '' : 'none';

  if (hasRating) {
    const ratingsNote = d.ratings_through
      ? `Ratings based on SAM results through ${d.ratings_through}`
      : '';
    document.getElementById('rating-body').innerHTML =
      pageHeader(d, ratingsNote, dateStr) + courtTable(d.rating, true);
    document.getElementById('comparison-body').innerHTML =
      pageHeader(d, ratingsNote, dateStr) + comparisonTable(d.comparison);
  } else {
    document.getElementById('rating-body').innerHTML = '';
    document.getElementById('comparison-body').innerHTML = '';
  }
}

function setTab(tab) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  document.querySelectorAll('.section').forEach(s => s.classList.toggle('active', s.dataset.section === tab));
}

document.querySelectorAll('.tab-btn').forEach(b => {
  b.addEventListener('click', () => setTab(b.dataset.tab));
});

const sel = document.getElementById('date-select');

// Determine "today" and whether the 8:15 AM cutoff has passed, in Mountain
// Standard Time (MST — America/Phoenix, no DST, matches the run_all.sh scrape cutoff).
// Before 8:15 AM on a play date, that date's session hasn't been played yet,
// so it still counts as the next play date. After 8:15 AM, it's considered
// played and the default should roll forward to the following date.
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
// Fallback: if all dates removed, restore the last (most recent past) one
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

setTab('den');
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
    all_data = {}
    for snap_file in sorted(HISTORY_DIR.glob("*.json")):
        date_str = snap_file.stem
        all_data[date_str] = json.loads(snap_file.read_text())

    if not all_data:
        print("No assignment snapshots found.")
        return None

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
            .replace("%%JSON%%", json.dumps(all_data, separators=(",", ":")))
            .replace("%%DATES%%", json.dumps(dates)))

    no_shootout_dates = []
    if NO_SHOOTOUT_LOG.exists():
        with NO_SHOOTOUT_LOG.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            no_shootout_dates = [row["date"] for row in reader if row.get("date")]

    html = html.replace("%%NO_SHOOTOUT_DATES%%", json.dumps(no_shootout_dates))

    # Inject dropdown options via the empty <select> the JS fills at runtime —
    # simplest to just set them server-side too so the first render has a value.
    html = html.replace(
        '<select id="date-select"></select>',
        f'<select id="date-select">{"".join(options)}</select>',
    )

    OUT_DIR.mkdir(exist_ok=True)
    OUTPUT.write_text(html, encoding="utf-8")
    print(f"Saved: {OUTPUT}")
    return OUTPUT


if __name__ == "__main__":
    generate_viewer()
