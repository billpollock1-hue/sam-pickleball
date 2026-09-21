#!/usr/bin/env python3
"""
Compare Ratings — a dedicated standalone page for the point-to-point rating
comparison feature, separated out from the Leaderboard page (which it used
to share a URL with) so the two have visually distinct layouts. Reads the
same workbook the Leaderboard does.
"""

import json
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
      <div class="lg-note">Color intensity scales with the size of the rating change between the selected From and To dates.</div>
    </div>
  </div>

  <div class="wrap">
    <div class="compare-bar">
      <span class="compare-label">Compare ratings:</span>
      <label for="fromDateSelect">From</label>
      <select id="fromDateSelect" onchange="updateDeltaColumn()"></select>
      <label for="toDateSelect">To</label>
      <select id="toDateSelect" onchange="updateDeltaColumn()"></select>
    </div>
    <div id="coverageStatus" class="compare-status"></div>

    <table>
      <thead>
        <tr><th class="nm">Player</th><th class="sortable" data-col="1" onclick="sortTable(1)">Current Rating<span class="sort-arrow"></span></th><th class="sortable" data-col="2" id="fromHeader" onclick="sortTable(2)">From<span class="sort-arrow"></span></th><th class="sortable" data-col="3" id="toHeader" onclick="sortTable(3)">To<span class="sort-arrow"></span></th><th class="sortable" data-col="4" onclick="sortTable(4)">&Delta; Rating<span class="sort-arrow"></span></th></tr>
      </thead>
      <tbody>{rows}
      </tbody>
    </table>
  </div>
</div>

<script>
const RATING_DATES = {rating_dates_json};
const RATING_GRID = {rating_grid_json};

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
    const nameCell = document.querySelector(`td.nm[data-player="${{CSS.escape(player)}}"]`);

    if (!grid || fromIdx < 0 || toIdx < 0) {{
      cell.textContent = "\u2014";
      cell.style.color = "";
      if (nameCell) nameCell.style.color = "";
      if (fromCell) fromCell.textContent = "\u2014";
      if (toCell) toCell.textContent = "\u2014";
      return;
    }}
    const fromVal = grid[fromIdx];
    const toVal = grid[toIdx];
    if (fromCell) fromCell.textContent = fromVal !== null ? fromVal : "\u2014";
    if (toCell) toCell.textContent = toVal !== null ? toVal : "\u2014";
    if (fromVal === null || toVal === null) {{
      cell.textContent = "\u2014";
      cell.style.color = "";
      if (nameCell) nameCell.style.color = "";
      return;
    }}
    captured++;
    const delta = toVal - fromVal;
    const color = deltaColor(delta);
    cell.textContent = (delta > 0 ? "+" : "") + delta;
    cell.style.color = color;
    if (nameCell) nameCell.style.color = color;
  }});

  const pct = cells.length ? Math.round((captured / cells.length) * 100) : 0;
  document.getElementById("coverageStatus").textContent =
    `Based on the From/To dates above, ${{pct}}% of current leaderboard players are captured in the \u0394 Rating column. To increase that percentage, choose a more current From date and/or To date.`;
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
