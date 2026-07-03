#!/usr/bin/env python3
"""
Slim public leaderboard — a phone-friendly HTML view of the essential
leaderboard columns, published alongside the other shareable pages.
Reads the workbook produced by the engine, so run after the model build.
"""

from pathlib import Path

import pandas as pd

ENGINE_DIR = Path(__file__).resolve().parent
REPO_ROOT = ENGINE_DIR.parent
XLSX_PATH = REPO_ROOT / "output" / "pickleball_model_latest.xlsx"
OUT_PATH = REPO_ROOT / "output" / "leaderboard.html"

lb = pd.read_excel(XLSX_PATH, sheet_name="Leaderboard")
data_through = pd.to_datetime(lb["Last Played"]).max().strftime("%B %-d, %Y")

def signed(v, decimals=0, suffix=""):
    """Format a signed value with pos/neg coloring."""
    if pd.isna(v):
        return "<td>—</td>"
    val = round(float(v), decimals)
    if decimals == 0:
        val = int(val)
    cls = "pos" if val > 0 else ("neg" if val < 0 else "")
    sign = "+" if val > 0 else ""
    return f'<td class="{cls}">{sign}{val}{suffix}</td>'

rows = ""
for _, r in lb.iterrows():
    last = pd.Timestamp(r["Last Played"]).strftime("%b %-d")
    trend = str(r.get("Trend", "")).strip()
    trend = "" if trend in ("—", "-", "nan") else trend
    vs_exp = signed(100 * r["Win % vs Expected"], 0, "%")
    pt_diff = signed(r["Avg Point Diff"], 1)
    edge = signed(r["Avg Matchup Edge"], 0)
    rows += f"""
      <tr>
        <td class="rk">{int(r['Rank'])}</td>
        <td class="nm">{r['Player']} <span class="tr">{trend}</span></td>
        <td class="rt">{int(r['Player Rating'])}</td>
        <td>{round(100 * r['Win %'])}%</td>
        {vs_exp}
        {pt_diff}
        {edge}
        <td class="lp">{last}</td>
      </tr>"""

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SAM Leaderboard</title>
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

  .wrap {{ max-width: 640px; margin: 0 auto; padding: 14px 10px 40px; }}

  .filter {{
    width: 100%; padding: 9px 14px; margin-bottom: 12px;
    border: 1px solid #c6d2e0; border-radius: 22px; font-size: 15px;
    background: #fff;
  }}
  .filter:focus {{ outline: 2px solid var(--blue-mid); border-color: transparent; }}

  table {{ width: 100%; border-collapse: collapse; background: #fff;
           border-radius: 10px; overflow: hidden; box-shadow: 0 1px 4px rgba(31,78,121,0.10); }}
  th {{
    background: var(--blue-mid); color: #fff; padding: 9px 8px;
    font-size: 12.5px; text-align: center; position: sticky; top: 0;
  }}
  th.nm {{ text-align: left; }}
  td {{ padding: 8px 8px; text-align: center; font-size: 14px;
        border-bottom: 1px solid #e8edf3; white-space: nowrap; }}
  td.rk {{ color: #8a97a8; font-size: 13px; width: 34px; }}
  td.nm {{ text-align: left; font-weight: 600; }}
  td.nm .tr {{ font-weight: normal; font-size: 12px; }}
  td.rt {{ font-weight: bold; color: var(--blue-dark); }}
  td.pos {{ color: #276221; }}
  td.neg {{ color: #9C3B1B; }}
  tr:nth-child(even) td {{ background: #f2f6fb; }}
  tr.top3 td.rk {{ color: #C9A84C; font-weight: bold; }}

  .foot {{ margin-top: 12px; font-size: 12px; color: #8a97a8; text-align: center; line-height: 1.6; }}
  .foot a {{ color: var(--blue-mid); }}

  @media (max-width: 430px) {{
    td.lp, th.lp {{ display: none; }}
    td {{ font-size: 13.5px; padding: 7px 6px; }}
  }}
</style>
</head>
<body>

<header>
  <h1>SAM Leaderboard</h1>
  <p>Modified Elo ratings &middot; through {data_through}</p>
</header>

<div class="wrap">
  <input class="filter" id="q" type="search" placeholder="Find a player&hellip;" oninput="filterRows()">
  <table>
    <thead>
      <tr><th>#</th><th class="nm">Player</th><th>Rating</th><th>Win %</th><th>Win % vs Expected</th><th>Avg Point Diff</th><th>Avg Matchup Edge</th><th class="lp">Last Played</th></tr>
    </thead>
    <tbody id="body">{rows}
    </tbody>
  </table>
  <p class="foot">
    All stats reflect each player's last 60 rated games (fewer for newer players).<br>
    Qualification: at least 24 rated games within the past 180 days.<br>
    <a href="index.html">All charts &amp; tools</a> &middot; updated after every play date
  </p>
</div>

<script>
  const rows = Array.from(document.querySelectorAll('#body tr'));
  rows.slice(0, 3).forEach(r => r.classList.add('top3'));
  function filterRows() {{
    const q = document.getElementById('q').value.trim().toLowerCase();
    rows.forEach(r => {{
      const name = r.querySelector('.nm').textContent.toLowerCase();
      r.style.display = (!q || name.includes(q)) ? '' : 'none';
    }});
  }}
</script>
</body>
</html>
"""

OUT_PATH.write_text(html, encoding="utf-8")
print(f"Saved: {OUT_PATH} ({len(lb)} players, through {data_through})")
