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

# ── Session Effects badges: strong/weak starter & finisher ─────────────────
# Uses the existing "Session Effects" sheet. G1 Effect = this player's
# game-1 win-rate gap (actual vs expected) relative to their own G2-5
# baseline gap — negative means they underperform their own norm in the
# first game of the day (slow starter). G6 Effect = same idea for the
# last game of the day (positive = strong finisher, negative = fades).
# Badges only apply with >=15 play-dates at that position, to keep small
# samples from producing noisy badges; near-zero effects stay unbadged
# (read as "neutral" — no icon shown).

SE_MIN_DATES = 15
SE_EFFECT_THRESHOLD = 0.15

se = pd.read_excel(XLSX_PATH, sheet_name="Session Effects")

def se_badge(effect, n, strong_icon, weak_icon):
    if pd.isna(effect) or pd.isna(n) or n < SE_MIN_DATES:
        return "", ""
    if effect >= SE_EFFECT_THRESHOLD:
        return strong_icon, f"Strong starter/finisher: {effect:+.0%} vs. own norm ({int(n)} play dates)"
    if effect <= -SE_EFFECT_THRESHOLD:
        return weak_icon, f"Weak starter/finisher: {effect:+.0%} vs. own norm ({int(n)} play dates)"
    return "", ""

session_badges = {}
for _, s in se.iterrows():
    start_icon, start_title = se_badge(s["G1 Effect"], s["G1 Games"], "🚀", "🐢")
    finish_icon, finish_title = se_badge(s["G6 Effect"], s["G6 Games"], "🎯", "📉")
    session_badges[s["Player"]] = {
        "start_icon": start_icon, "start_title": start_title.replace("starter/finisher", "starter"),
        "finish_icon": finish_icon, "finish_title": finish_title.replace("starter/finisher", "finisher"),
    }

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

    sb = session_badges.get(r["Player"], {})
    badge_html = ""
    if sb.get("start_icon"):
        badge_html += f' <span class="se" title="{sb["start_title"]}">{sb["start_icon"]}</span>'
    if sb.get("finish_icon"):
        badge_html += f' <span class="se" title="{sb["finish_title"]}">{sb["finish_icon"]}</span>'

    rows += f"""
      <tr>
        <td class="rk">{int(r['Rank'])}</td>
        <td class="nm">{r['Player']} <span class="tr">{trend}</span>{badge_html}</td>
        <td class="rt">{int(r['Player Rating'])}</td>
        <td>{round(100 * r['Win %'])}%</td>
        {vs_exp}
        {pt_diff}
        {edge}
        <td class="lp">{last}</td>
      </tr>"""


# ── Perspective Scale: empirical win% / avg margin by team rating gap ──────
# Uses the last 120 days of Player_Game_Log. Each match has one row per
# player (4 rows/match); team_pre_rating and opp_team_pre_rating are
# identical for both players on a team, so filtering to
# team_pre_rating > opp_team_pre_rating isolates exactly one row per match
# — the favorite's perspective, with matching gap size, win/loss, and
# margin. Buckets start fine (25 pts) and auto-merge upward until each has
# a minimum sample size, so sparse large-gap buckets widen automatically
# instead of showing noisy small-N results.

BUCKET_MIN_N = 20
FINE_BUCKET_WIDTH = 50

log = pd.read_excel(XLSX_PATH, sheet_name="Player_Game_Log")
log["posted_dt"] = pd.to_datetime(log["posted_dt"], errors="coerce")

rated = log[log["include_in_ratings"] == "Yes"].dropna(subset=["posted_dt"])
window_end = rated["posted_dt"].max()
window_start = window_end - pd.Timedelta(days=120)
recent = rated[(rated["posted_dt"] >= window_start) & (rated["posted_dt"] <= window_end)]

favorite = recent[recent["team_pre_rating"] > recent["opp_team_pre_rating"]].copy()
favorite["gap"] = favorite["team_pre_rating"] - favorite["opp_team_pre_rating"]
favorite["fine_bucket"] = (favorite["gap"] // FINE_BUCKET_WIDTH).astype(int)

fine_groups = favorite.groupby("fine_bucket").agg(
    n=("is_win", "size"),
    wins=("is_win", "sum"),
    margin_sum=("margin", "sum"),
).sort_index()

perspective_buckets = []
carry_n, carry_wins, carry_margin_sum, carry_lo = 0, 0, 0.0, None
for fine_idx, row in fine_groups.iterrows():
    lo = fine_idx * FINE_BUCKET_WIDTH
    if carry_lo is None:
        carry_lo = lo
    carry_n += int(row["n"])
    carry_wins += int(row["wins"])
    carry_margin_sum += float(row["margin_sum"])
    if carry_n >= BUCKET_MIN_N:
        hi = lo + FINE_BUCKET_WIDTH
        perspective_buckets.append({
            "lo": carry_lo, "hi": hi, "n": carry_n,
            "win_pct": carry_wins / carry_n,
            "avg_margin": carry_margin_sum / carry_n,
        })
        carry_n, carry_wins, carry_margin_sum, carry_lo = 0, 0, 0.0, None

# Merge any leftover thin trailing bucket into the last completed one
if carry_n > 0:
    if perspective_buckets:
        last = perspective_buckets[-1]
        combined_n = last["n"] + carry_n
        combined_wins = last["win_pct"] * last["n"] + carry_wins
        combined_margin_sum = last["avg_margin"] * last["n"] + carry_margin_sum
        last["hi"] = carry_lo + FINE_BUCKET_WIDTH
        last["n"] = combined_n
        last["win_pct"] = combined_wins / combined_n
        last["avg_margin"] = combined_margin_sum / combined_n
    else:
        perspective_buckets.append({
            "lo": carry_lo, "hi": carry_lo + FINE_BUCKET_WIDTH, "n": carry_n,
            "win_pct": carry_wins / carry_n,
            "avg_margin": carry_margin_sum / carry_n,
        })

perspective_rows = ""
perspective_bars = ""
for b in perspective_buckets:
    label = f'{b["lo"]}\u2013{b["hi"]}'
    win_pct_display = round(100 * b["win_pct"])
    margin_display = round(b["avg_margin"], 1)
    margin_sign = "+" if margin_display > 0 else ""
    perspective_rows += f"""
      <tr>
        <td class="ps-gap">{label}</td>
        <td class="ps-win">{win_pct_display}%</td>
        <td class="ps-margin">{margin_sign}{margin_display}</td>
        <td class="ps-n">{b['n']}</td>
      </tr>"""
    bar_width = max(2, win_pct_display)
    perspective_bars += f"""
      <div class="ps-bar-row">
        <span class="ps-bar-label">{label}</span>
        <div class="ps-bar-track"><div class="ps-bar-fill" style="width:{bar_width}%"></div></div>
        <span class="ps-bar-pct">{win_pct_display}%</span>
      </div>"""

perspective_window_label = f'{window_start.strftime("%b %-d")}\u2013{window_end.strftime("%b %-d, %Y")}'


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

  .page {{ max-width: 1240px; margin: 0 auto; padding: 14px 10px 40px;
           display: flex; gap: 18px; align-items: flex-start; flex-wrap: wrap; }}

  .wrap {{ flex: 1 1 600px; min-width: 0; order: 2; }}

  .back-badge {{ position: fixed; top: 10px; left: 10px; z-index: 1000;
                 background: #1F4E79; color: #fff; font-size: 12px;
                 padding: 6px 12px; border-radius: 6px; text-decoration: none;
                 box-shadow: 0 1px 4px rgba(0,0,0,0.2); }}
  .back-badge:hover {{ background: #163a5c; }}

  /* ── Icon decoder (left panel) ── */
  .decoder {{ flex: 1 1 220px; max-width: 250px; order: 1; }}
  .dc-card {{ background: #fff; border-radius: 10px; box-shadow: 0 1px 4px rgba(31,78,121,0.10);
              padding: 14px 14px 16px; }}
  .dc-title {{ font-size: 14px; font-weight: 700; color: var(--blue-dark); margin-bottom: 10px; }}
  .dc-row {{ display: flex; align-items: flex-start; gap: 8px; margin-bottom: 9px; font-size: 12px; line-height: 1.4; }}
  .dc-icon {{ flex-shrink: 0; width: 20px; text-align: center; }}

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
  td.nm .se {{ font-size: 12px; cursor: default; }}
  td.rt {{ font-weight: bold; color: var(--blue-dark); }}
  td.pos {{ color: #276221; }}
  td.neg {{ color: #9C3B1B; }}
  tr:nth-child(even) td {{ background: #f2f6fb; }}

  .foot {{ margin-top: 12px; font-size: 12px; color: #8a97a8; text-align: center; line-height: 1.6; }}
  .foot a {{ color: var(--blue-mid); }}

  /* ── Perspective Scale sidebar ── */
  .sidebar {{ flex: 1 1 260px; max-width: 300px; order: 3; }}
  .ps-card {{ background: #fff; border-radius: 10px; box-shadow: 0 1px 4px rgba(31,78,121,0.10);
              padding: 14px 14px 16px; }}
  .ps-title {{ font-size: 14px; font-weight: 700; color: var(--blue-dark); margin-bottom: 2px; }}
  .ps-sub {{ font-size: 11px; color: #8a97a8; margin-bottom: 10px; line-height: 1.5; }}

  .ps-table {{ width: 100%; border-collapse: collapse; margin-bottom: 14px; }}
  .ps-table th {{ background: var(--blue-light); color: var(--blue-dark); font-size: 11px;
                  padding: 6px 4px; position: static; }}
  .ps-table td {{ font-size: 12.5px; padding: 5px 4px; border-bottom: 1px solid #e8edf3; }}
  .ps-gap {{ text-align: left; color: #555; }}
  .ps-win {{ font-weight: 700; color: var(--blue-dark); }}
  .ps-margin {{ color: #555; }}
  .ps-n {{ color: #aab4c0; font-size: 11px; }}

  .ps-bar-row {{ display: flex; align-items: center; gap: 6px; margin-bottom: 5px; }}
  .ps-bar-label {{ font-size: 10.5px; color: #8a97a8; width: 52px; flex-shrink: 0; }}
  .ps-bar-track {{ flex: 1; background: #eef2f7; border-radius: 4px; height: 10px; overflow: hidden; }}
  .ps-bar-fill {{ background: var(--blue-mid); height: 100%; border-radius: 4px; }}
  .ps-bar-pct {{ font-size: 10.5px; color: var(--blue-dark); font-weight: 600; width: 30px; text-align: right; flex-shrink: 0; }}

  @media (max-width: 430px) {{
    td.lp, th.lp {{ display: none; }}
    td {{ font-size: 13.5px; padding: 7px 6px; }}
  }}
  @media (max-width: 900px) {{
    .decoder {{ max-width: none; flex-basis: 100%; order: 2; }}
    .wrap {{ order: 1; }}
    .sidebar {{ max-width: none; flex-basis: 100%; order: 3; }}
  }}
</style>
</head>
<body>

<a href="index.html" class="back-badge">&larr; Menu</a>

<header>
  <h1>SAM Leaderboard</h1>
  <p>Modified Elo ratings &middot; through {data_through}</p>
</header>

<div class="page">
  <div class="decoder">
    <div class="dc-card">
      <div class="dc-title">Icon Decoder</div>
      <div class="dc-row"><span class="dc-icon">🔥</span><span>Hot streak — last 15 games running 6+ pts hotter (win% vs. expected) than their prior 45-game baseline; requires 60+ total rated games and a game within the last 14 days</span></div>
      <div class="dc-row"><span class="dc-icon">🧊</span><span>Cold streak — last 15 games running 6+ pts colder (win% vs. expected) than their prior 45-game baseline; requires 60+ total rated games and a game within the last 14 days</span></div>
      <div class="dc-row"><span class="dc-icon">🚀</span><span>Strong starter — Game 1 win% vs. expected runs 15+ pts above own mid-session norm (15+ play dates)</span></div>
      <div class="dc-row"><span class="dc-icon">🐢</span><span>Slow starter — Game 1 win% vs. expected runs 15+ pts below own mid-session norm (15+ play dates)</span></div>
      <div class="dc-row"><span class="dc-icon">🎯</span><span>Strong finisher — last game win% vs. expected runs 15+ pts above own mid-session norm (15+ play dates)</span></div>
      <div class="dc-row"><span class="dc-icon">📉</span><span>Fades late — last game win% vs. expected runs 15+ pts below own mid-session norm (15+ play dates)</span></div>
    </div>
  </div>

  <div class="wrap">
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
      🚀/🐢 strong/weak starter &middot; 🎯/📉 strong/weak finisher (15+ play dates, hover for detail)<br>
      <a href="index.html">All charts &amp; tools</a> &middot; updated after every play date
    </p>
  </div>

  <div class="sidebar">
    <div class="ps-card">
      <div class="ps-title">Perspective Scale</div>
      <div class="ps-sub">
        Favorite's win % and avg. margin by team rating gap.<br>
        Actual results, {perspective_window_label} (120 days).
      </div>
      <table class="ps-table">
        <thead><tr><th class="ps-gap" style="text-align:left">Gap</th><th>Win%</th><th>Margin</th><th>N</th></tr></thead>
        <tbody>{perspective_rows}
        </tbody>
      </table>
      <div class="ps-bars">{perspective_bars}
      </div>
    </div>
  </div>
</div>

<script>
</script>
</body>
</html>
"""

OUT_PATH.write_text(html, encoding="utf-8")
print(f"Saved: {OUT_PATH} ({len(lb)} players, through {data_through})")
print(f"Perspective Scale: {len(perspective_buckets)} buckets from {len(favorite)} favorite-side games in last 120 days")
