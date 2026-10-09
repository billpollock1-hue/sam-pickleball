#!/usr/bin/env python3
"""
Compare Ratings — a dedicated standalone page for the point-to-point rating
comparison feature, separated out from the Leaderboard page (which it used
to share a URL with) so the two have visually distinct layouts. Reads the
same workbook the Leaderboard does.
"""

import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

ENGINE_DIR = Path(__file__).resolve().parent
REPO_ROOT = ENGINE_DIR.parent
XLSX_PATH = REPO_ROOT / "output" / "pickleball_model_latest.xlsx"
OUT_PATH = REPO_ROOT / "output" / "compare_ratings.html"

lb = pd.read_excel(XLSX_PATH, sheet_name="Leaderboard")
data_through = pd.to_datetime(lb["Last Played"]).max().strftime("%B %-d, %Y")

hist = pd.read_excel(XLSX_PATH, sheet_name="Rating History")
rating_dates = [c for c in hist.columns if c != "Player"]
rating_dates_sorted = sorted(rating_dates)
rating_grid = {}
for _, hr in hist.iterrows():
    rating_grid[str(hr["Player"])] = [
        (int(hr[d]) if pd.notna(hr[d]) and hr[d] != "" else None) for d in rating_dates_sorted
    ]
rating_dates_json = json.dumps(rating_dates_sorted)
rating_grid_json = json.dumps(rating_grid)

# ── Games played per player, one date string per rated game ──────────────
# Sourced from Player_Game_Log (same sheet build_player_history.py uses) so
# the Games Played column only counts games that actually moved a rating --
# the same games the Delta Rating column reflects.
pgl = pd.read_excel(XLSX_PATH, sheet_name="Player_Game_Log")
pgl["posted_dt"] = pd.to_datetime(pgl["posted_dt"])
pgl["date_str"] = pgl["posted_dt"].dt.strftime("%Y-%m-%d")
pgl_rated = pgl[pgl["include_in_ratings"].astype(str).str.strip() == "Yes"]
game_dates = defaultdict(list)
for _, gr in pgl_rated.sort_values("posted_dt").iterrows():
    game_dates[str(gr["player"])].append(gr["date_str"])
game_dates_json = json.dumps(game_dates)

rows = ""
for _, r in lb.iterrows():
    name_attr = str(r["Player"]).replace('"', "&quot;")
    rows += f"""
      <tr>
        <td class="nm" data-player="{name_attr}">{r['Player']}</td>
        <td class="current-rt">{int(r['Player Rating'])}</td>
        <td class="from-rating" data-player="{name_attr}">&#8212;</td>
        <td class="to-rating" data-player="{name_attr}">&#8212;</td>
        <td class="delta" data-player="{name_attr}">&#8212;</td>
        <td class="games-played" data-player="{name_attr}">&#8212;</td>
      </tr>"""

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ratings Change — SAM Shootout</title>
<style>
  :root {{
    --blue-dark: #1F4E79;
    --blue-mid:  #2E75B6;
    --blue-light:#D6E4F0;
    --text:      #333333;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: Calibri, Arial, sans-serif; color: var(--text); background: #f7f9fc; }}

  header {{
    background: var(--blue-dark); color: #fff;
    padding: 20px 16px; text-align: center;
  }}
  header h1 {{ font-size: 22px; }}
  header p {{ font-size: 13px; opacity: 0.85; margin-top: 4px; }}

  .back-badge {{ position: fixed; top: 10px; left: 10px; z-index: 1000;
                 background: #1F4E79; color: #fff; font-size: 12px;
                 padding: 6px 12px; border-radius: 6px; text-decoration: none;
                 box-shadow: 0 1px 4px rgba(0,0,0,0.2); border: none; cursor: pointer; }}
  .back-badge:hover {{ background: #163a5c; }}
  #freshness-hint {{ padding: 6px 16px; font-size: 11px; color: #888;
                     background: #fafafa; border-bottom: 1px solid #e8edf3; text-align: center; }}

  .page {{ max-width: 1240px; margin: 0 auto; padding: 14px 10px 40px;
           display: flex; gap: 18px; align-items: flex-start; flex-wrap: wrap; }}

  .legend {{ flex: 1 1 220px; max-width: 250px; order: 1; }}
  .lg-card {{ background: #fff; border-radius: 10px; box-shadow: 0 1px 4px rgba(31,78,121,0.10);
              padding: 14px; }}
  .lg-title {{ font-size: 14px; font-weight: bold; color: var(--blue-dark); margin-bottom: 10px; }}
  .lg-row {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; font-size: 12px; }}
  .lg-swatch {{ width: 22px; height: 14px; border-radius: 3px; flex-shrink: 0; }}
  .lg-note {{ font-size: 11px; color: #666; margin-top: 10px; line-height: 1.4; }}

  .wrap {{ flex: 1 1 600px; min-width: 0; order: 2; }}

  .compare-bar {{ background: #fff; border-radius: 10px; box-shadow: 0 1px 4px rgba(31,78,121,0.10);
                  padding: 14px; margin-bottom: 10px; font-size: 13px; }}
  .compare-label {{ font-weight: bold; color: var(--blue-dark); margin-right: 8px; }}
  .compare-bar select {{ margin: 0 10px 0 4px; padding: 4px 8px; border-radius: 5px;
                          border: 1px solid #ccc; font-size: 13px; }}
  .compare-status {{ font-size: 12px; color: #666; padding: 0 14px 10px; }}

  .quick-range {{ margin-top: 10px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }}
  .quick-range-label {{ font-weight: bold; color: var(--blue-dark); margin-right: 2px; font-size: 13px; }}
  .quick-range button {{ background: var(--blue-light); color: var(--blue-dark); border: 1px solid #c3d6e8;
                          border-radius: 14px; padding: 5px 12px; font-size: 12.5px; cursor: pointer;
                          font-family: Calibri, Arial, sans-serif; transition: background 0.15s; }}
  .quick-range button:hover {{ background: #c3d9ee; }}
  .quick-range button.active {{ background: var(--blue-mid); color: #fff; border-color: var(--blue-mid); }}

  table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 10px;
           overflow: hidden; box-shadow: 0 1px 4px rgba(31,78,121,0.10); }}
  th {{ background: var(--blue-mid); color: #fff; padding: 9px 8px; font-size: 12.5px;
        text-align: center; position: sticky; top: 0; }}
  th.nm {{ text-align: left; }}
  td {{ padding: 8px 8px; font-size: 14px; text-align: center; border-bottom: 1px solid #eef2f7;
        white-space: nowrap; }}
  td.nm {{ text-align: left; font-weight: 600; }}
  td.delta {{ font-weight: 700; }}
  th.sortable {{ cursor: pointer; user-select: none; }}
  th.sortable:hover {{ background: var(--blue-dark); }}
  .sort-arrow {{ display: inline-block; width: 10px; margin-left: 2px; }}
</style>
</head>
<body>

<a class="back-badge" href="index.html">&#8592; Menu</a>

<header>
  <h1>Ratings Change</h1>
  <p>See how ratings have changed between two dates for all leaderboard players &middot; through {data_through}</p>
</header>
<div id="freshness-hint">Tap Refresh anytime to make sure you're seeing the latest data.</div>

<div class="page">
  <div class="legend">
    <div class="lg-card">
      <div class="lg-title">Delta Color Key</div>
      <div class="lg-row"><div class="lg-swatch" style="background:#0d5c2e;"></div><span>Large gain</span></div>
      <div class="lg-row"><div class="lg-swatch" style="background:#4a9960;"></div><span>Small gain</span></div>
      <div class="lg-row"><div class="lg-swatch" style="background:#888888;"></div><span>No meaningful change</span></div>
      <div class="lg-row"><div class="lg-swatch" style="background:#c05a5a;"></div><span>Small loss</span></div>
      <div class="lg-row"><div class="lg-swatch" style="background:#a01515;"></div><span>Large loss</span></div>
      <div class="lg-note">Color intensity scales with the size of the rating change between the selected From and To dates.<br><br>An asterisk (*) on a From/To rating means the player didn't play on that exact date &mdash; it's their most recent rating as of that date instead.</div>
    </div>
  </div>

  <div class="wrap">
    <div class="compare-bar">
      <span class="compare-label">Compare ratings:</span>
      <label for="fromDateSelect">From</label>
      <select id="fromDateSelect" onchange="clearQuickRangeActive(); updateDeltaColumn()"></select>
      <label for="toDateSelect">To</label>
      <select id="toDateSelect" onchange="clearQuickRangeActive(); updateDeltaColumn()"></select>
      <div class="quick-range">
        <span class="quick-range-label">Quick range:</span>
        <button type="button" onclick="setQuickRange(7, this)">Last 7 days</button>
        <button type="button" onclick="setQuickRange(14, this)">Last 14 days</button>
        <button type="button" onclick="setQuickRange(30, this)">Last 30 days</button>
        <button type="button" onclick="setQuickRange(60, this)">Last 60 days</button>
      </div>
    </div>
    <div id="coverageStatus" class="compare-status"></div>

    <table>
      <thead>
        <tr><th class="nm">Player</th><th class="sortable" data-col="1" onclick="sortTable(1)">Current Rating<span class="sort-arrow"></span></th><th class="sortable" data-col="2" id="fromHeader" onclick="sortTable(2)">From<span class="sort-arrow"></span></th><th class="sortable" data-col="3" id="toHeader" onclick="sortTable(3)">To<span class="sort-arrow"></span></th><th class="sortable" data-col="4" onclick="sortTable(4)">&Delta; Rating<span class="sort-arrow"></span></th><th class="sortable" data-col="5" onclick="sortTable(5)" title="Rated games played between the selected From and To dates">Games<span class="sort-arrow"></span></th></tr>
      </thead>
      <tbody>{rows}
      </tbody>
    </table>
  </div>
</div>

<script>
const RATING_DATES = {rating_dates_json};
const RATING_GRID = {rating_grid_json};
const GAME_DATES = {game_dates_json};

// -- Freshness: force a genuine network fetch on every real navigation to
// this page, bypassing any browser/CDN cache. If this load doesn't already
// carry our cache-bust marker, immediately redirect to a URL that does --
// GitHub Pages' CDN (and browsers) cache by full URL including query
// string, so a unique timestamp guarantees a cache miss. Same pattern as
// the Leaderboard page: no per-date state to preserve on redirect, since
// the From/To selects are populated fresh from RATING_DATES on load
// rather than driven by the URL.
(function () {{
  const params = new URLSearchParams(location.search);
  if (!params.has('_cb')) {{
    params.set('_cb', Date.now());
    location.replace(location.pathname + '?' + params.toString());
  }}
}})();

function forceRefresh() {{
  const params = new URLSearchParams(location.search);
  params.set('_cb', Date.now());
  location.replace(location.pathname + '?' + params.toString());
}}

// Periodic freshness re-check for tabs left open a while.
setInterval(forceRefresh, 5 * 60 * 1000);

function populateDateSelects() {{
  const fromSel = document.getElementById("fromDateSelect");
  const toSel = document.getElementById("toDateSelect");

  let firstAnyIdx = RATING_DATES.length;
  for (let i = 0; i < RATING_DATES.length; i++) {{
    const anyData = Object.values(RATING_GRID).some(grid => grid[i] !== null);
    if (anyData) {{ firstAnyIdx = i; break; }}
  }}
  const usefulDates = RATING_DATES.slice(firstAnyIdx);

  usefulDates.forEach(d => {{
    const o1 = document.createElement("option");
    o1.value = d; o1.text = d;
    fromSel.appendChild(o1);
  }});
  [...usefulDates].reverse().forEach(d => {{
    const o2 = document.createElement("option");
    o2.value = d; o2.text = d;
    toSel.appendChild(o2);
  }});

  const DEFAULT_COVERAGE_PCT = 0.75;
  const allGrids = Object.values(RATING_GRID);
  const totalPlayers = allGrids.length;
  let defaultFromIdx = RATING_DATES.length - 1;
  for (let i = firstAnyIdx; i < RATING_DATES.length; i++) {{
    const coverage = allGrids.filter(grid => grid[i] !== null).length / totalPlayers;
    if (coverage >= DEFAULT_COVERAGE_PCT) {{ defaultFromIdx = i; break; }}
  }}

  if (usefulDates.length) {{
    fromSel.value = RATING_DATES[defaultFromIdx];
    toSel.value = usefulDates[usefulDates.length - 1];
  }}
}}

function clearQuickRangeActive() {{
  document.querySelectorAll('.quick-range button').forEach(b => b.classList.remove('active'));
}}

function setQuickRange(days, btn) {{
  const fromSel = document.getElementById('fromDateSelect');
  const toSel = document.getElementById('toDateSelect');
  if (!fromSel.options.length || !toSel.options.length) return;

  // toSel is populated most-recent-first, so its first option is the latest
  // date with any rating data -- that's always the right default "To".
  const latest = toSel.options[0].value;
  toSel.value = latest;

  // fromSel is populated oldest-first; walk forward and take the earliest
  // date that still falls within the requested trailing window.
  const targetTime = new Date(latest + 'T00:00:00Z').getTime() - days * 86400000;
  const fromOptions = Array.from(fromSel.options).map(o => o.value);
  let chosen = fromOptions[0];
  for (const d of fromOptions) {{
    if (new Date(d + 'T00:00:00Z').getTime() >= targetTime) {{ chosen = d; break; }}
  }}
  fromSel.value = chosen;

  clearQuickRangeActive();
  if (btn) btn.classList.add('active');
  updateDeltaColumn();
}}

function deltaColor(delta) {{
  const CAP = 100;
  const NEUTRAL_ZONE = 5; // deltas within +/-5 read as "no meaningful change"
  if (Math.abs(delta) <= NEUTRAL_ZONE) return "#888888";

  const intensity = Math.min((Math.abs(delta) - NEUTRAL_ZONE) / (CAP - NEUTRAL_ZONE), 1);
  if (delta > 0) {{
    // Readable medium green (#4a9960) -> dark saturated green (#0d5c2e)
    const r = Math.round(74 - intensity * (74 - 13));
    const g = Math.round(153 - intensity * (153 - 92));
    const b = Math.round(96 - intensity * (96 - 46));
    return `rgb(${{r}}, ${{g}}, ${{b}})`;
  }} else {{
    // Readable medium red (#c05a5a) -> dark saturated red (#a01515)
    const r = Math.round(192 - intensity * (192 - 160));
    const g = Math.round(90 - intensity * (90 - 21));
    const b = Math.round(90 - intensity * (90 - 21));
    return `rgb(${{r}}, ${{g}}, ${{b}})`;
  }}
}}

function findRating(grid, idx) {{
  if (idx < 0) return {{ value: null, exact: false, atIdx: -1 }};
  if (grid[idx] !== null) return {{ value: grid[idx], exact: true, atIdx: idx }};
  for (let i = idx - 1; i >= 0; i--) {{
    if (grid[i] !== null) return {{ value: grid[i], exact: false, atIdx: i }};
  }}
  return {{ value: null, exact: false, atIdx: -1 }};
}}

function countGames(player, fromDate, toDate) {{
  const dates = GAME_DATES[player];
  if (!dates || !fromDate || !toDate) return 0;
  return dates.filter(d => d > fromDate && d <= toDate).length;
}}

function updateDeltaColumn() {{
  const fromDate = document.getElementById("fromDateSelect").value;
  const toDate = document.getElementById("toDateSelect").value;
  const fromIdx = RATING_DATES.indexOf(fromDate);
  const toIdx = RATING_DATES.indexOf(toDate);

  document.getElementById("fromHeader").textContent = fromDate || "From";
  document.getElementById("toHeader").textContent = toDate || "To";

  let captured = 0;
  const cells = document.querySelectorAll("td.delta");
  cells.forEach(cell => {{
    const player = cell.getAttribute("data-player");
    const grid = RATING_GRID[player];
    const fromCell = document.querySelector(`td.from-rating[data-player="${{CSS.escape(player)}}"]`);
    const toCell = document.querySelector(`td.to-rating[data-player="${{CSS.escape(player)}}"]`);
    const gamesCell = document.querySelector(`td.games-played[data-player="${{CSS.escape(player)}}"]`);
    const nameCell = document.querySelector(`td.nm[data-player="${{CSS.escape(player)}}"]`);

    if (!grid || fromIdx < 0 || toIdx < 0) {{
      cell.textContent = "\u2014";
      cell.style.color = "";
      if (nameCell) nameCell.style.color = "";
      if (fromCell) {{ fromCell.textContent = "\u2014"; fromCell.title = ""; }}
      if (toCell) {{ toCell.textContent = "\u2014"; toCell.title = ""; }}
      if (gamesCell) gamesCell.textContent = "\u2014";
      return;
    }}

    const from = findRating(grid, fromIdx);
    const to = findRating(grid, toIdx);

    if (fromCell) {{
      fromCell.textContent = from.value !== null ? from.value + (from.exact ? "" : "*") : "\u2014";
      fromCell.title = (from.value !== null && !from.exact)
        ? `Last rating as of ${{RATING_DATES[from.atIdx]}} \u2014 no games on ${{fromDate}}`
        : "";
    }}
    if (toCell) {{
      toCell.textContent = to.value !== null ? to.value + (to.exact ? "" : "*") : "\u2014";
      toCell.title = (to.value !== null && !to.exact)
        ? `Last rating as of ${{RATING_DATES[to.atIdx]}} \u2014 no games on ${{toDate}}`
        : "";
    }}

    // Games played is independent of whether a From/To rating exists -- a
    // player whose first game falls after the From date (no prior rating to
    // carry forward) can still have played real games in the window, so this
    // must not be gated on from.value/to.value being non-null.
    if (gamesCell) gamesCell.textContent = countGames(player, fromDate, toDate);

    if (from.value === null || to.value === null) {{
      cell.textContent = "\u2014";
      cell.style.color = "";
      if (nameCell) nameCell.style.color = "";
      return;
    }}

    captured++;
    const delta = to.value - from.value;
    const color = deltaColor(delta);
    cell.textContent = (delta > 0 ? "+" : "") + delta;
    cell.style.color = color;
    if (nameCell) nameCell.style.color = color;
  }});

  const pct = cells.length ? Math.round((captured / cells.length) * 100) : 0;
  document.getElementById("coverageStatus").textContent =
    `Based on the From/To dates above, ${{pct}}% of current leaderboard players have a rating for both dates (an asterisk marks one carried forward from a player's last game before that date). To increase that percentage, choose a more current From date and/or To date.`;
}}

let sortState = {{ col: -1, asc: true }};

function sortTable(colIndex) {{
  const tbody = document.querySelector("table tbody");
  const rows = Array.from(tbody.querySelectorAll("tr"));

  if (sortState.col === colIndex) {{
    sortState.asc = !sortState.asc;
  }} else {{
    sortState.col = colIndex;
    sortState.asc = true;
  }}

  rows.sort((a, b) => {{
    const aVal = parseFloat(a.children[colIndex].textContent.trim());
    const bVal = parseFloat(b.children[colIndex].textContent.trim());
    const aNum = isNaN(aVal) ? -Infinity : aVal;
    const bNum = isNaN(bVal) ? -Infinity : bVal;
    return sortState.asc ? aNum - bNum : bNum - aNum;
  }});

  rows.forEach(row => tbody.appendChild(row));

  document.querySelectorAll("th.sortable").forEach(th => {{
    const arrow = th.querySelector(".sort-arrow");
    const thCol = parseInt(th.getAttribute("data-col"), 10);
    arrow.textContent = thCol === sortState.col ? (sortState.asc ? "\u25B2" : "\u25BC") : "";
  }});
}}

populateDateSelects();
updateDeltaColumn();
</script>
</body>
</html>
"""

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
OUT_PATH.write_text(html, encoding="utf-8")
print(f"Saved: {OUT_PATH}")
