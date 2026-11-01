#!/usr/bin/env python3
"""
History File Adjustments -- a public log of corrections made to the
underlying game history file (data/master_history_raw.csv), such as
player-substitution fixes, so anyone can see exactly what was changed,
when, why, and how it moved ratings.

Each entry comes from data/history_adjustments.json. To log a new
adjustment: append an object to that JSON array (id, date_logged,
affected_dates, title, description, requested_by, games_changed,
rating_impact -- a list of {player, before, after, delta, direct}),
then re-run this script. "direct": true means the player was actually
on court in one of the changed games that day; false means their
number moved only as a ripple effect through later games against
someone whose rating changed.

Self-contained HTML, no server required -- matches the rest of the
site (same header/card visual language as docs/index.html).
"""

import json
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
REPO_ROOT = ENGINE_DIR.parent
DATA_PATH = REPO_ROOT / "data" / "history_adjustments.json"
OUT_PATH = REPO_ROOT / "output" / "history_adjustments.html"

if DATA_PATH.exists():
    with open(DATA_PATH, encoding="utf-8") as f:
        adjustments = json.load(f)
else:
    adjustments = []

adjustments = sorted(adjustments, key=lambda a: a.get("date_logged", ""), reverse=True)


def fmt_date(iso):
    try:
        y, m, d = iso.split("-")
        months = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        return f"{months[int(m)]} {int(d)}, {y}"
    except Exception:
        return iso


def fmt_date_short(iso):
    try:
        y, m, d = iso.split("-")
        return f"{int(m)}/{int(d)}/{y[2:]}"
    except Exception:
        return iso


def fmt_delta(d):
    sign = "+" if d > 0 else ("" if d == 0 else "-")
    return f"{sign}{abs(d):.1f}"


def render_impact_rows(impact):
    rows = []
    for row in sorted(impact, key=lambda r: abs(r["delta"]), reverse=True):
        delta = row["delta"]
        cls = "pos" if delta > 0 else ("neg" if delta < 0 else "zero")
        tag = (
            '<span class="tag tag-direct">on court</span>'
            if row.get("direct")
            else '<span class="tag tag-ripple">ripple</span>'
        )
        rows.append(
            f"<tr><td>{row['player']}</td>"
            f"<td>{tag}</td>"
            f"<td class='num'>{row['before']:.1f}</td>"
            f"<td class='num'>{row['after']:.1f}</td>"
            f"<td class='num {cls}'>{fmt_delta(delta)}</td></tr>"
        )
    return "\n".join(rows)


def render_adjustment(a):
    dates = ", ".join(fmt_date(d) for d in a.get("affected_dates", []))
    impact = a.get("rating_impact", [])
    direct_n = sum(1 for r in impact if r.get("direct"))
    ripple_n = len(impact) - direct_n
    rows_html = render_impact_rows(impact)
    snap_date = fmt_date_short(a.get("date_logged", ""))
    return f"""
  <section class="entry">
    <div class="entry-head">
      <h2>{a.get('title','Untitled adjustment')}</h2>
      <span class="logged">Logged {fmt_date(a.get('date_logged',''))}</span>
    </div>
    <p class="meta">Affected play date{'s' if len(a.get('affected_dates', [])) != 1 else ''}: <strong>{dates}</strong>
      &nbsp;.&nbsp; {a.get('games_changed', 0)} game(s) changed
      &nbsp;.&nbsp; requested by {a.get('requested_by', 'unknown')}</p>
    <p class="desc">{a.get('description','')}</p>
    <p class="impact-summary">Rating impact: <strong>{direct_n}</strong> player(s) were actually on
      court in a changed game; <strong>{ripple_n}</strong> more moved only as a downstream ripple
      through later games. Changes under 0.05 are not shown.</p>
    <table class="impact">
      <thead><tr><th>Player</th><th></th><th>Before (as of {snap_date})</th><th>After (as of {snap_date})</th><th>Change</th></tr></thead>
      <tbody>
{rows_html}
      </tbody>
    </table>
  </section>
"""


entries_html = "\n".join(render_adjustment(a) for a in adjustments) if adjustments else """
  <p class="empty">No adjustments logged yet.</p>
"""

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>History File Adjustments -- SAM Pickleball</title>
<style>
  :root {{
    --blue-dark: #1F4E79;
    --blue-mid:  #2E75B6;
    --teal:      #2A9D8F;
    --rust:      #b3543a;
    --text:      #333333;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: Calibri, Arial, sans-serif; color: var(--text); background: #f7f9fc; }}
  header {{ background: var(--blue-dark); color: #fff; padding: 22px 18px; text-align: center; }}
  header h1 {{ font-size: 22px; }}
  header p {{ font-size: 13.5px; opacity: 0.85; margin-top: 6px; }}
  header a {{ color: #cfe0f2; font-size: 12.5px; }}
  main {{ max-width: 760px; margin: 0 auto; padding: 20px 16px 48px; display: flex; flex-direction: column; gap: 18px; }}
  .entry {{ background: #fff; border: 1px solid #dbe4ee; border-left: 5px solid var(--teal); border-radius: 8px; padding: 16px 18px; }}
  .entry-head {{ display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 6px; }}
  .entry h2 {{ font-size: 16.5px; color: var(--blue-dark); }}
  .logged {{ font-size: 11.5px; color: #8a97a8; white-space: nowrap; }}
  .meta {{ font-size: 12.5px; color: #666; margin-top: 6px; }}
  .desc {{ font-size: 13.5px; line-height: 1.5; margin-top: 10px; }}
  .impact-summary {{ font-size: 12.5px; color: #555; margin-top: 10px; }}
  table.impact {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 13px; }}
  table.impact th {{ text-align: left; font-size: 11.5px; color: #8a97a8; font-weight: 600; padding: 6px 8px; border-bottom: 1px solid #e4eaf1; }}
  table.impact td {{ padding: 6px 8px; border-bottom: 1px solid #eef2f7; }}
  table.impact td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  table.impact td.pos {{ color: #1b7a4b; font-weight: 600; }}
  table.impact td.neg {{ color: var(--rust); font-weight: 600; }}
  table.impact td.zero {{ color: #999; }}
  .tag {{ font-size: 10px; font-weight: 700; letter-spacing: 0.3px; border-radius: 4px; padding: 2px 6px; white-space: nowrap; }}
  .tag-direct {{ background: rgba(42, 157, 143, 0.18); color: #1d7267; }}
  .tag-ripple {{ background: rgba(136, 136, 136, 0.15); color: #777; }}
  .empty {{ text-align: center; color: #888; padding: 40px 0; }}
  footer {{ text-align: center; font-size: 12px; color: #8a97a8; padding: 16px; }}
</style>
</head>
<body>
<header>
  <h1>History File Adjustments</h1>
  <p>Corrections made to the underlying game history, and exactly how each one moved ratings.</p>
  <p><a href="index.html">&larr; Back to SAM Pickleball</a></p>
</header>
<main>
{entries_html}
</main>
<footer>SAM Pickleball -- History File Adjustments</footer>
</body>
</html>
"""

OUT_PATH.parent.mkdir(exist_ok=True)
with open(OUT_PATH, "w", encoding="utf-8") as f:
    f.write(html)

print(f"Saved: {OUT_PATH} ({len(adjustments)} adjustment(s) logged)")
