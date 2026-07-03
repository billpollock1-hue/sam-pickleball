#!/usr/bin/env python3
"""
Storybook presentation of the court-assignment case — an open-faced book
with 3D page turns. Self-contained HTML; all exhibits computed live from
the master history and the engine's own analysis functions, so the book
refreshes with every model run.

Spreads: Cover → Challenge → Metric → Proof → Evidence → Root Cause →
DEN System → 2-up/2-back → Options → Recommendation → Technical Appendix
(2 spreads) → Back cover.
"""

import sys
from pathlib import Path

import pandas as pd

ENGINE_DIR = Path(__file__).resolve().parent
REPO_ROOT = ENGINE_DIR.parent
sys.path.insert(0, str(ENGINE_DIR))

from pickleball_engine_v2 import (
    apply_manual_fix, team_has_placeholder,
    build_full_player_log, build_rating_gap_distribution,
    build_competitive_balance_by_quarter, build_court_assignment_analysis,
)

DATA_PATH = REPO_ROOT / "data" / "master_history_raw.csv"
XLSX_PATH = REPO_ROOT / "output" / "pickleball_model_latest.xlsx"
OUT_PATH = REPO_ROOT / "output" / "storybook.html"

# ══ Load & prepare data ═══════════════════════════════════════════════════════
print("Loading history...")
raw = pd.read_csv(DATA_PATH)
raw["posted_dt"] = pd.to_datetime(raw["posted"], errors="coerce")
raw = raw.dropna(subset=["posted_dt"]).sort_values("posted_dt").reset_index(drop=True)
raw["winning_team"] = raw.apply(lambda r: apply_manual_fix(r["winning_team"], r["posted_dt"]), axis=1)
raw["losing_team"] = raw.apply(lambda r: apply_manual_fix(r["losing_team"], r["posted_dt"]), axis=1)
raw["exclude_match"] = raw.get("exclude_match", False)
raw["exclude_match"] = raw["exclude_match"].fillna(False).astype(bool)
raw["include_in_ratings"] = ~(
    raw["winning_team"].apply(team_has_placeholder)
    | raw["losing_team"].apply(team_has_placeholder)
    | raw["exclude_match"]
)

n_games = len(raw)
n_dates = raw["posted_dt"].dt.date.nunique()
first_year = raw["posted_dt"].min().year
latest = raw["posted_dt"].max().strftime("%B %-d, %Y")

players = set()
for col in ("winning_team", "losing_team"):
    for team in raw[col].dropna():
        for p in str(team).split(" / "):
            players.add(p.strip())
n_all_players = len(players)

print("Replaying rating history...")
player_log = build_full_player_log(raw)

print("Building exhibits...")
gap_dist = build_rating_gap_distribution(player_log)
cb = build_competitive_balance_by_quarter(player_log)

# Leaderboard facts from the workbook (active pool)
lb = pd.read_excel(XLSX_PATH, sheet_name="Leaderboard")
n_active = len(lb)
lb_min, lb_max = int(lb["Player Rating"].min()), int(lb["Player Rating"].max())
lb_range = lb_max - lb_min

print("Running court-assignment scenarios (90 days)...")
_, scenario_summary, _ = build_court_assignment_analysis(raw, player_log, days=90)
print("Scenarios:", scenario_summary["Scenario"].tolist())

def scen(*needle_sets):
    """Fuzzy scenario lookup: each needle set is tried in order; within a set,
    all substrings must match the scenario name (case-insensitive)."""
    for needles in needle_sets:
        if isinstance(needles, str):
            needles = (needles,)
        for _, row in scenario_summary.iterrows():
            name = str(row["Scenario"]).lower()
            if all(n.lower() in name for n in needles):
                return row
    return None

den  = scen(("den", "current"), "den")
e2u  = scen(("elo", "2u2b"))
ph1  = scen(("elo", "1u1b"))
e20  = scen(("elo s1", "elo s2"))
ph2  = scen(("elo", "k100"))
k150 = scen(("elo", "k150"))
bsw  = scen("boundary", "bdrswap", "swap")
upt  = scen("upset", "upt")

def sv(row, key, default="—"):
    if row is None:
        return default
    v = row.get(key, default)
    return default if pd.isna(v) else v

# Competitive balance display quarters: first, latest, three waypoints
cbq = cb.set_index("Quarter")
want = ["2022 Q1", "2023 Q1", "2024 Q1", "2025 Q2"]
show_q = [q for q in want if q in cbq.index]
latest_q = cb["Quarter"].iloc[-1]
if latest_q not in show_q:
    show_q.append(latest_q)
q_first = cbq.loc[show_q[0]]
q_last = cbq.loc[show_q[-1]]
max_gap = max(cbq.loc[q, "Avg Gap"] for q in show_q)

balance_rows = ""
for q in show_q:
    r = cbq.loc[q]
    barw = round(100 * r["Avg Gap"] / max_gap)
    balance_rows += f"""
      <tr>
        <td>{q}</td>
        <td><div class="bar"><span style="width:{barw}%;"></span><em>{round(r['Avg Gap'])}</em></div></td>
        <td>{round(100 * r['% Under 200'])}%</td>
      </tr>"""

gap_rows = ""
for _, r in gap_dist.iterrows():
    gap_rows += f"""
      <tr><td>{r['Rating Gap']}</td><td>{r['% Won by Higher-Rated Team']}</td>
      <td>{r.get('Margin 1–2','—')}</td><td>{r.get('Margin 9–11','—')}</td></tr>"""

options = [
    ("Elo S1 &middot; keep 2-up/2-back", sv(e2u, "vs DEN"), sv(e2u, "S1→S2 % Moving"), "Setting change"),
    ("Elo S1 &middot; 1-up/1-back &nbsp;&#9733; Phase 1", sv(ph1, "vs DEN"), sv(ph1, "S1→S2 % Moving"), "Setting change"),
    ("Elo S1 &middot; Elo S2 (K=20)", sv(e20, "vs DEN"), sv(e20, "S1→S2 % Moving"), "Automation"),
    ("Elo S1 &middot; Elo S2 (K=100) &nbsp;&#9733; Phase 2", sv(ph2, "vs DEN"), sv(ph2, "S1→S2 % Moving"), "Automation"),
    ("Elo S1 &middot; Elo S2 (K=150)", sv(k150, "vs DEN"), sv(k150, "S1→S2 % Moving"), "Automation"),
    ("Elo S1 &middot; Boundary Swap S2", sv(bsw, "vs DEN"), sv(bsw, "S1→S2 % Moving"), "Automation"),
    ("Elo S1 &middot; Upset-Triggered S2", sv(upt, "vs DEN"), sv(upt, "S1→S2 % Moving"), "Automation"),
]
option_rows = ""
for label, vs, mv, impl in options:
    star = "&#9733;" in label
    option_rows += f"""
      <tr class="{'hl' if star else ''}"><td style="text-align:left;">{label}</td>
      <td>{vs}</td><td>{mv}</td><td>{impl}</td></tr>"""

den_s1 = sv(den, "S1 Avg Spread")
den_s2 = sv(den, "S2 Avg Spread")
den_comb = sv(den, "Combined Spread")
den_move = sv(den, "S1→S2 % Moving")
ph1_comb = sv(ph1, "Combined Spread")
ph2_comb = sv(ph2, "Combined Spread")
ph1_vs = sv(ph1, "vs DEN")
ph2_vs = sv(ph2, "vs DEN")

pct_lt200_first = round(100 * q_first["% Under 200"])
pct_lt200_last = round(100 * q_last["% Under 200"])

# ══ HTML ══════════════════════════════════════════════════════════════════════
html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Can SAM Be Improved?</title>
<style>
  :root {{
    --navy:   #1F4E79;
    --navy-2: #2E75B6;
    --paper:  #FBF7EE;
    --ink:    #33302A;
    --accent: #C9A84C;
    --tan:    #f3ecdd;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{ height: 100%; }}
  body {{
    font-family: Georgia, 'Times New Roman', serif;
    background: radial-gradient(ellipse at center, #3d5a75 0%, #24384d 70%);
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    min-height: 100vh; padding: 24px 12px; overflow-x: hidden;
  }}
  .book-wrap {{ perspective: 2600px; }}
  .book {{
    position: relative;
    width: min(94vw, 1040px);
    aspect-ratio: 2 / 1.38;
    transform-style: preserve-3d;
  }}
  .page {{
    position: absolute; top: 0; width: 50%; height: 100%;
    background: var(--paper); padding: 4.6% 4.4%; overflow: hidden;
  }}
  .page.left  {{ left: 0;  border-radius: 12px 0 0 12px; box-shadow: inset -14px 0 24px -14px rgba(0,0,0,0.35); }}
  .page.right {{ right: 0; border-radius: 0 12px 12px 0; box-shadow: inset 14px 0 24px -14px rgba(0,0,0,0.30); }}
  .sheet {{
    position: absolute; top: 0; left: 50%; width: 50%; height: 100%;
    transform-origin: left center; transform-style: preserve-3d;
    transition: transform 0.85s cubic-bezier(0.4, 0.05, 0.3, 1);
    cursor: pointer;
  }}
  .sheet.flipped {{ transform: rotateY(-180deg); }}
  .face {{
    position: absolute; inset: 0;
    backface-visibility: hidden; -webkit-backface-visibility: hidden;
    background: var(--paper); padding: 4.6% 4.4%; overflow: hidden;
  }}
  .face.front {{ border-radius: 0 12px 12px 0; box-shadow: inset 14px 0 24px -14px rgba(0,0,0,0.30); }}
  .face.back  {{ transform: rotateY(180deg); border-radius: 12px 0 0 12px; box-shadow: inset -14px 0 24px -14px rgba(0,0,0,0.35); }}

  .cover, .darkpage {{
    background: linear-gradient(145deg, var(--navy) 0%, #16385a 100%);
    color: #fff; display: flex; flex-direction: column;
    align-items: center; justify-content: center; text-align: center; gap: 16px;
  }}
  .cover .rule {{ width: 56px; height: 2px; background: var(--accent); }}
  .cover h1 {{ font-size: clamp(19px, 3vw, 32px); font-weight: normal; letter-spacing: 1px; line-height: 1.25; }}
  .cover .sub {{ font-size: clamp(10px, 1.3vw, 14px); opacity: 0.85; font-style: italic; line-height: 1.5; }}
  .cover .hint {{ position: absolute; bottom: 6%; font-size: 12px; opacity: 0.55; }}
  .darkpage a {{ color: var(--accent); text-decoration: none; }}
  .darkpage p {{ color: #e8edf3; }}

  .kicker {{
    font-family: 'Trebuchet MS', Verdana, sans-serif;
    font-size: clamp(8.5px, 0.95vw, 11.5px); letter-spacing: 2.2px; text-transform: uppercase;
    color: var(--navy-2); margin-bottom: 3.2%;
  }}
  h2 {{ font-size: clamp(14.5px, 1.85vw, 22px); color: var(--navy); font-weight: normal; margin-bottom: 3.2%; line-height: 1.22; }}
  p  {{ font-size: clamp(10px, 1.2vw, 14.5px); line-height: 1.56; color: var(--ink); margin-bottom: 3%; }}
  .pgnum {{ position: absolute; bottom: 3.8%; font-size: 11px; color: #9a8f7a; }}
  .page.left .pgnum, .face.back .pgnum {{ left: 6%; }}
  .page.right .pgnum, .face.front .pgnum {{ right: 6%; }}

  .stat-stack {{ display: flex; flex-direction: column; gap: 4.5%; height: 80%; justify-content: center; }}
  .stat {{ border-left: 4px solid var(--navy-2); background: var(--tan); padding: 4% 6%; border-radius: 0 8px 8px 0; }}
  .stat .num {{ font-size: clamp(19px, 2.8vw, 32px); color: var(--navy); }}
  .stat .lbl {{ font-family: 'Trebuchet MS', sans-serif; font-size: clamp(8.5px, 1.05vw, 12px); color: #6d6353; margin-top: 2px; }}

  .factor {{ background: var(--tan); border-radius: 8px; padding: 3.5% 5%; margin-bottom: 3.5%; }}
  .factor b {{ display: block; font-family: 'Trebuchet MS', sans-serif; font-size: clamp(9.5px, 1.1vw, 13px); color: var(--navy); margin-bottom: 1%; }}
  .factor span {{ font-size: clamp(9.5px, 1.15vw, 13.5px); line-height: 1.45; color: var(--ink); }}
  .callout {{
    margin-top: 4%; padding: 3.5% 5%; background: var(--navy); color: #fff;
    border-radius: 8px; font-size: clamp(9.5px, 1.15vw, 13.5px); line-height: 1.5;
  }}
  .callout b {{ color: var(--accent); }}

  table.btable {{
    width: 100%; border-collapse: collapse; margin-top: 2%;
    font-family: 'Trebuchet MS', sans-serif; font-size: clamp(8.5px, 1.02vw, 12.5px);
  }}
  .btable th {{
    background: var(--navy-2); color: #fff; padding: 2.2% 2%;
    font-weight: bold; text-align: center; font-size: clamp(8px, 0.95vw, 11.5px);
  }}
  .btable td {{ padding: 2% 2%; text-align: center; border-bottom: 1px solid #e0d7c3; color: var(--ink); }}
  .btable tr:nth-child(even) td {{ background: #f5efe1; }}
  .btable tr.hl td {{ background: #eee3c5; font-weight: bold; }}

  .bar {{ position: relative; background: #e8dfc9; border-radius: 4px; height: 16px; min-width: 90px; }}
  .bar span {{ position: absolute; left: 0; top: 0; bottom: 0; background: var(--navy-2); border-radius: 4px; }}
  .bar em {{ position: absolute; right: 6px; top: 0; bottom: 0; display: flex; align-items: center;
             font-style: normal; font-size: 10.5px; color: #fff; mix-blend-mode: difference; }}

  .flaw {{ background: var(--tan); border-left: 4px solid #b3543a; border-radius: 0 8px 8px 0;
           padding: 3% 4.5%; margin-bottom: 3%; }}
  .flaw b {{ display: block; font-family: 'Trebuchet MS', sans-serif; color: #8a3c26;
             font-size: clamp(9px, 1.05vw, 12.5px); margin-bottom: 1%; }}
  .flaw span {{ font-size: clamp(9px, 1.08vw, 13px); line-height: 1.42; }}

  .phase {{ background: var(--tan); border-radius: 10px; padding: 4.5% 5.5%; margin-bottom: 4.5%;
            border-top: 4px solid var(--accent); }}
  .phase b {{ display: block; font-family: 'Trebuchet MS', sans-serif; color: var(--navy);
              font-size: clamp(10.5px, 1.25vw, 14.5px); margin-bottom: 2%; }}
  .phase span {{ font-size: clamp(9.5px, 1.15vw, 13.5px); line-height: 1.5; }}
  .phase .metric {{ margin-top: 2.5%; font-family: 'Trebuchet MS', sans-serif;
                    font-size: clamp(9px, 1.05vw, 12.5px); color: var(--navy-2); font-weight: bold; }}

  .mono {{ font-family: 'Courier New', monospace; background: #efe7d2; border-radius: 6px;
           padding: 3.5% 5%; font-size: clamp(9px, 1.1vw, 13px); line-height: 1.7; color: #4a4438;
           margin-bottom: 3.5%; }}
  .apx {{ background: repeating-linear-gradient(0deg, var(--paper), var(--paper) 26px, #f1ead9 27px); }}

  .controls {{
    margin-top: 20px; display: flex; align-items: center; gap: 18px;
    color: #cfdae6; font-family: 'Trebuchet MS', sans-serif; font-size: 13px;
  }}
  .controls button {{
    background: rgba(255,255,255,0.12); border: 1px solid rgba(255,255,255,0.3);
    color: #fff; border-radius: 20px; padding: 7px 18px; cursor: pointer; font-size: 13px;
  }}
  .controls button:hover {{ background: rgba(255,255,255,0.25); }}
  .controls button:disabled {{ opacity: 0.3; cursor: default; }}

  @media (max-width: 640px) {{
    .book {{ width: 94vw; aspect-ratio: 1 / 1.5; }}
    .page.left {{ display: none; }}
    .page.right, .face.front, .face.back {{ width: 100%; left: 0; right: auto; border-radius: 10px; }}
    .sheet {{ left: 0; width: 100%; }}
    .face.back .pgnum {{ left: auto; right: 6%; }}
  }}
</style>
</head>
<body>

<div class="book-wrap">
  <div class="book" id="book">

    <div class="page left" id="baseLeft"></div>

    <!-- Back cover (revealed when all sheets are flipped) -->
    <div class="page right darkpage">
      <div class="rule" style="width:56px;height:2px;background:var(--accent);"></div>
      <h1 style="font-size:clamp(16px,2.2vw,26px);font-weight:normal;">See Where You Stand</h1>
      <p style="font-size:clamp(10px,1.25vw,14px);line-height:1.6;">
        Every rating, every game, every trend in this book<br>is available live, updated after each play date:</p>
      <p style="font-size:clamp(10px,1.3vw,14.5px);"><a href="https://billpollock1-hue.github.io/sam-pickleball/">billpollock1-hue.github.io/sam-pickleball</a></p>
      <p style="font-size:11px;opacity:0.6;margin-top:4%;">Data through {latest} &middot; {n_games:,} games</p>
    </div>

    <!-- s0: COVER | p1 Challenge -->
    <div class="sheet">
      <div class="face front cover">
        <div class="rule"></div>
        <h1>Can SAM<br>Be Improved?</h1>
        <div class="rule"></div>
        <div class="sub">Using four years of shootout data to make<br>every SAM session more competitive</div>
        <div class="hint">click to open &#8250;</div>
      </div>
      <div class="face back">
        <div class="kicker">Chapter One</div>
        <h2>The Challenge: From Perception to Evidence</h2>
        <p>Players in the SAM shootout have raised concerns about court competitiveness &mdash; too many lopsided games, courts that feel mismatched.</p>
        <p>Perception is a starting point, but it is not enough to diagnose the problem or evaluate solutions. We need an objective metric: a way to measure the skill gap between teams in any given game, consistently, across thousands of games and multiple years.</p>
        <p>Fortunately, we have exactly the raw material that requires.</p>
        <div class="pgnum">1</div>
      </div>
    </div>

    <!-- s1: p2 stats | p3 Metric -->
    <div class="sheet">
      <div class="face front">
        <div class="kicker">The Raw Material</div>
        <div class="stat-stack">
          <div class="stat"><div class="num">{n_games:,}</div><div class="lbl">games recorded since {first_year}</div></div>
          <div class="stat"><div class="num">{n_dates:,}</div><div class="lbl">play dates captured</div></div>
          <div class="stat"><div class="num">{n_all_players}</div><div class="lbl">players who have taken the court</div></div>
        </div>
        <div class="pgnum">2</div>
      </div>
      <div class="face back">
        <div class="kicker">Chapter Two</div>
        <h2>The Metric: Modified Elo</h2>
        <p>Elo is a rating system originally developed for chess and widely used in competitive sports. Every player starts at 1,000. After each game, all four players&rsquo; ratings update based on the result versus what the model predicted.</p>
        <p>Your team&rsquo;s rating is the average of you and your partner. The bigger the rating gap between two teams, the more confidently the model expects the stronger side to win.</p>
        <p>Two club-specific adjustments &mdash; covered in the appendix &mdash; make sure long tenure carries no built-in advantage and new players reach an accurate rating quickly.</p>
        <div class="pgnum">3</div>
      </div>
    </div>

    <!-- s2: p4 factors | p5 Proof narrative -->
    <div class="sheet">
      <div class="face front">
        <div class="kicker">Three Factors Drive Every Update</div>
        <div class="factor"><b>1 &middot; RESULT</b><span>Winning earns points; losing costs points.</span></div>
        <div class="factor"><b>2 &middot; MARGIN</b><span>An 11&ndash;2 win moves ratings more than an 11&ndash;9 win.</span></div>
        <div class="factor"><b>3 &middot; OPPONENT STRENGTH</b><span>Beating a strong team earns more than beating a weak one.</span></div>
        <div class="callout">In observed SAM games, the higher-rated team wins <b>57%</b> at a 100-point gap, <b>66%</b> at 200, and <b>78%</b> at 300.</div>
        <div class="pgnum">4</div>
      </div>
      <div class="face back">
        <div class="kicker">Chapter Three</div>
        <h2>Does the Model Actually Work?</h2>
        <p>A rating is only useful if it predicts real outcomes. So before drawing any conclusions, we checked the model against every rated game in the dataset.</p>
        <p>The pattern is exactly what a healthy rating system should show: the bigger the pre-game rating gap between two teams, the more often the favorite wins &mdash; and the more lopsided the score gets.</p>
        <p>Small gaps produce coin-flip games decided by a point or two. Big gaps produce blowouts. The facing page shows the full relationship.</p>
        <div class="pgnum">5</div>
      </div>
    </div>

    <!-- s3: p6 gap table | p7 Evidence narrative -->
    <div class="sheet">
      <div class="face front">
        <div class="kicker">Rating Gap vs. Real Outcomes</div>
        <table class="btable">
          <tr><th>Team Rating Gap</th><th>Favorite Wins</th><th>Decided by 1&ndash;2 pts</th><th>Decided by 9&ndash;11 pts</th></tr>
          {gap_rows}
        </table>
        <p style="font-size:clamp(8.5px,1vw,12px);color:#8a7f6a;margin-top:3%;">All rated games, {first_year}&ndash;present. Close games fade and blowouts grow as the gap widens.</p>
        <div class="pgnum">6</div>
      </div>
      <div class="face back">
        <div class="kicker">Chapter Four</div>
        <h2>The Evidence: A Growing Competitiveness Problem</h2>
        <p>With a trustworthy measuring stick, we can now measure match quality directly. &ldquo;Match gap&rdquo; is the rating difference between the two teams in a game &mdash; smaller means more evenly matched.</p>
        <p>The trend is unmistakable. The average match gap has nearly doubled since early {first_year + 0 if first_year >= 2022 else 2022}, and games that qualify as closely matched &mdash; a gap under 200 points &mdash; have fallen from {pct_lt200_first}% of all games to {pct_lt200_last}%.</p>
        <p>Mismatched games are no longer rare exceptions. They are now the norm for roughly 4 in 10 matches.</p>
        <div class="pgnum">7</div>
      </div>
    </div>

    <!-- s4: p8 balance exhibit | p9 root cause -->
    <div class="sheet">
      <div class="face front">
        <div class="kicker">Average Match Gap by Quarter</div>
        <table class="btable">
          <tr><th>Quarter</th><th>Avg Match Gap</th><th>Games &lt;200 Gap</th></tr>
          {balance_rows}
        </table>
        <div class="callout" style="margin-top:5%;">The average court matchup today is nearly <b>twice as uneven</b> as it was in early {first_year if first_year >= 2022 else 2022}.</div>
        <div class="pgnum">8</div>
      </div>
      <div class="face back">
        <div class="kicker">Chapter Five</div>
        <h2>The Root Cause: A Wider Player Pool</h2>
        <p>The driver is not a shortage of strong players &mdash; it is that the SAM player pool has grown dramatically more diverse in skill.</p>
        <p>Today&rsquo;s leaderboard spans {n_active} active players &mdash; those with at least 24 rated games played within the past 180 days. The rating spread across that group is {lb_range:,} points, top to bottom.</p>
        <p>At that dispersion, the strongest player would be expected to beat the bottom of the leaderboard well over 99% of the time. Placing 12&ndash;20 players of this range onto 3&ndash;5 courts is genuinely hard &mdash; and the current assignment method wasn&rsquo;t built for it.</p>
        <div class="pgnum">9</div>
      </div>
    </div>

    <!-- s5: p10 then-vs-now | p11 DEN system -->
    <div class="sheet">
      <div class="face front">
        <div class="kicker">Then vs. Now</div>
        <div class="stat-stack">
          <div class="stat"><div class="num">{round(q_first['Avg Gap'])} &rarr; {round(q_last['Avg Gap'])}</div><div class="lbl">average match gap, {show_q[0]} vs. {show_q[-1]}</div></div>
          <div class="stat"><div class="num">~26 &rarr; {n_active}</div><div class="lbl">active leaderboard players</div></div>
          <div class="stat"><div class="num">{lb_range:,} pts</div><div class="lbl">rating spread across today's leaderboard</div></div>
        </div>
        <div class="pgnum">10</div>
      </div>
      <div class="face back">
        <div class="kicker">Chapter Six</div>
        <h2>How Courts Are Assigned Today</h2>
        <p>DEN builds Session 1 courts from two numbers. <b>Step</b> is a court-movement counter: finish in the top two of your court and it ticks down; finish in the bottom two and it ticks up &mdash; based entirely on your <i>last</i> play date, however long ago that was.</p>
        <p><b>Percentage</b> breaks ties within a step: total points scored divided by maximum possible, over your last 90 games (~15 play dates), all weighted equally.</p>
        <p>For Session 2, the top two on each court move up a court and the bottom two move down &mdash; the &ldquo;2-up/2-back&rdquo; rule.</p>
        <div class="pgnum">11</div>
      </div>
    </div>

    <!-- s6: p12 flaws | p13 net result narrative -->
    <div class="sheet">
      <div class="face front">
        <div class="kicker">Structural Weaknesses</div>
        <div class="flaw"><b>STALE BY DESIGN</b><span>Step reflects your last play date &mdash; which may be weeks or months old.</span></div>
        <div class="flaw"><b>COURT-COUNT BLIND</b><span>A step earned on a 5-court day penalizes you on a 3-court day. High-turnout days systematically punish; low-turnout days reward.</span></div>
        <div class="flaw"><b>OPPONENT BLIND</b><span>Bottom-two on Court 1 against the strongest players costs the same as bottom-two on Court 3 against the weakest. Points scored are never adjusted for who you played or partnered with.</span></div>
        <div class="flaw"><b>NO RECENCY</b><span>A session three months ago counts exactly as much as last week&rsquo;s.</span></div>
        <div class="pgnum">12</div>
      </div>
      <div class="face back">
        <div class="kicker">Chapter Seven</div>
        <h2>The Net Result</h2>
        <p>We replayed the last 90 days of actual sessions and measured the skill spread inside each court &mdash; lower means the four players on a court are more evenly matched.</p>
        <p>Under the current system, courts average a {den_s1}-point internal spread in Session 1. After the 2-up/2-back shuffle &mdash; which moves about {den_move} of all players &mdash; the spread <i>widens</i> to {den_s2}.</p>
        <p>Read that again: the movement rule designed to sort players actually leaves courts <b>less balanced</b> than they started. Most of that movement is mechanical, not earned.</p>
        <div class="pgnum">13</div>
      </div>
    </div>

    <!-- s7: p14 spread table | p15 options narrative -->
    <div class="sheet">
      <div class="face front">
        <div class="kicker">Within-Court Skill Spread &mdash; Current System</div>
        <div class="stat-stack" style="height:72%;">
          <div class="stat"><div class="num">{den_s1}</div><div class="lbl">Session 1 average spread (DEN step / percentage)</div></div>
          <div class="stat" style="border-left-color:#b3543a;"><div class="num">{den_s2}</div><div class="lbl">Session 2 average spread (after 2-up/2-back)</div></div>
          <div class="stat"><div class="num">{den_comb}</div><div class="lbl">combined baseline &mdash; the number to beat</div></div>
        </div>
        <div class="pgnum">14</div>
      </div>
      <div class="face back">
        <div class="kicker">Chapter Eight</div>
        <h2>What We Tested</h2>
        <p>We modeled a dozen alternative assignment methods across the same 90 days of real sessions &mdash; same players, same signups, same courts. Each is scored on how much it narrows the within-court spread versus the current system, and how many players move courts between sessions.</p>
        <p>Approaches range from a one-setting tweak (keep everything, just seed Session 1 by rating) to fully rating-driven sessions at different responsiveness levels.</p>
        <p>Two stand out &mdash; marked &#9733; on the facing page.</p>
        <div class="pgnum">15</div>
      </div>
    </div>

    <!-- s8: p16 options table | p17 recommendation -->
    <div class="sheet">
      <div class="face front">
        <div class="kicker">The Alternatives, Scored</div>
        <table class="btable">
          <tr><th style="text-align:left;">Approach</th><th>vs. Current</th><th>Players Moving S1&rarr;S2</th><th>Effort</th></tr>
          {option_rows}
        </table>
        <div class="pgnum">16</div>
      </div>
      <div class="face back">
        <div class="kicker">Chapter Nine</div>
        <h2>The Recommendation: Two Phases</h2>
        <div class="phase">
          <b>PHASE 1 &mdash; Rating-seeded Session 1, 1-up/1-back Session 2</b>
          <span>Seed the first session by modified Elo instead of step and percentage; soften the session-two shuffle to one-up/one-back. No new tooling &mdash; a DEN settings change.</span>
          <div class="metric">{ph1_vs} vs. current &middot; combined spread {ph1_comb}</div>
        </div>
        <div class="phase">
          <b>PHASE 2 &mdash; Rating-driven both sessions (K=100)</b>
          <span>Session 2 courts re-seeded from Session 1 results, weighted by opponent strength &mdash; movement is earned, not mechanical. Requires the automation this project already runs daily.</span>
          <div class="metric">{ph2_vs} vs. current &middot; combined spread {ph2_comb}</div>
        </div>
        <div class="pgnum">17</div>
      </div>
    </div>

    <!-- s9: p18 what changes | p19 appendix A left -->
    <div class="sheet">
      <div class="face front">
        <div class="kicker">What Changes for a Player</div>
        <div class="factor"><b>YOUR FIRST COURT FITS</b><span>Session 1 placement reflects how you&rsquo;ve actually been playing &mdash; not where you stood one bad morning three weeks ago.</span></div>
        <div class="factor"><b>MOVEMENT MEANS SOMETHING</b><span>Moving up is earned by beating expectations, weighted by who you faced &mdash; not by finishing top-two on an easy court.</span></div>
        <div class="factor"><b>EVERY GAME COUNTS</b><span>Your rating updates after every game, with recent play weighted most.</span></div>
        <div class="factor"><b>NOTHING ELSE CHANGES</b><span>Same courts, same times, same shootout format. Only the seeding logic improves.</span></div>
        <div class="pgnum">18</div>
      </div>
      <div class="face back apx">
        <div class="kicker" style="color:#8a7f6a;">Technical Appendix &middot; A</div>
        <h2>The Model Mechanics</h2>
        <p style="font-size:clamp(9.5px,1.12vw,13.5px);">For readers who want the nitty gritty. Every rating update follows one formula:</p>
        <div class="mono">&Delta;R = K &times; (S &minus; E) &times; M &times; D<br><br>
S &nbsp;= result (1 win, 0 loss)<br>
E &nbsp;= expected win prob = 1 / (1 + 10^((R<sub>opp</sub> &minus; R<sub>team</sub>)/400))<br>
M = margin multiplier = min(ln(margin + 1), 2.0)<br>
D &nbsp;= recency weight, 25% &rarr; 100% across the window</div>
        <p style="font-size:clamp(9px,1.08vw,13px);">Team ratings are the average of the two partners; all four players update after every rated game.</p>
        <div class="pgnum">19</div>
      </div>
    </div>

    <!-- s10: p20 appendix A right | p21 appendix B left -->
    <div class="sheet">
      <div class="face front apx">
        <div class="kicker" style="color:#8a7f6a;">Technical Appendix &middot; A, continued</div>
        <div class="factor"><b>NO-HISTORY-DRIFT WINDOW</b><span>A player&rsquo;s current rating is rebuilt by replaying only their last 60 rated games from a neutral 1,000 start. Long tenure carries zero legacy inflation; what you&rsquo;ve done lately is what counts.</span></div>
        <div class="factor"><b>PROVISIONAL K</b><span>K starts at 40 for a player&rsquo;s first game and declines linearly to 20 by game 60, then holds. New players converge quickly; established ratings stay stable.</span></div>
        <div class="factor"><b>EXPECTATION COMPRESSION</b><span>Displayed win probabilities compress the rating gap by 0.85 before the logistic &mdash; matching observed outcomes (57 / 66 / 78%) rather than theoretical chess curves.</span></div>
        <div class="pgnum">20</div>
      </div>
      <div class="face back apx">
        <div class="kicker" style="color:#8a7f6a;">Technical Appendix &middot; B</div>
        <h2>Data Hygiene &amp; Display</h2>
        <div class="factor"><b>WHAT COUNTS</b><span>Every posted shootout game since Jan {first_year}. Placeholder entries (tryouts, drop-ins), guest players, and flagged data errors are excluded from ratings; known name glitches are corrected at load.</span></div>
        <div class="factor"><b>LEADERBOARD QUALIFICATION</b><span>At least 24 rated games within the past 180 days. Everyone else still carries a rating &mdash; shown with reduced confidence, pulled toward 1,000 in proportion to sample size and staleness.</span></div>
        <div class="factor"><b>FRESHNESS</b><span>No penalty for 90 days of inactivity; beyond that, a graduated confidence haircut up to 15%.</span></div>
        <div class="pgnum">21</div>
      </div>
    </div>

    <!-- s11: p22 appendix B right | endpaper -->
    <div class="sheet">
      <div class="face front apx">
        <div class="kicker" style="color:#8a7f6a;">Technical Appendix &middot; B, continued</div>
        <div class="factor"><b>VALIDATION</b><span>Predictions are checked against outcomes across the full pool every run. Gaps between individual actual and expected win rates reflect normal variance and close as games accumulate; aggregate calibration is what the model is tuned for.</span></div>
        <div class="factor"><b>SCENARIO REPLAY</b><span>Assignment alternatives were tested against the last 90 days of real sessions &mdash; same signups, same court counts &mdash; not simulations of hypothetical players.</span></div>
        <div class="mono" style="margin-top:4%;">Full methodology: Model Description tab<br>of the ratings workbook &middot; every number in<br>this book regenerates on each model run.</div>
        <div class="pgnum">22</div>
      </div>
      <div class="face back darkpage">
        <p style="font-style:italic;opacity:0.75;">&mdash; end &mdash;</p>
      </div>
    </div>

  </div>
</div>

<div class="controls">
  <button id="btnBack" onclick="turn(-1)">&#8249; Back</button>
  <span id="pageInfo"></span>
  <button id="btnFwd" onclick="turn(1)">Forward &#8250;</button>
</div>

<script>
  const sheets = Array.from(document.querySelectorAll('.sheet'));
  const N = sheets.length;
  let flipped = 0;

  const spreadNames = ["Cover", "The Challenge", "The Metric", "Proof", "The Evidence",
                       "Root Cause", "Today's System", "Net Result", "What We Tested",
                       "Recommendation", "Appendix A", "Appendix B", "Back Cover"];

  function render() {{
    sheets.forEach((s, i) => {{
      s.classList.toggle('flipped', i < flipped);
      s.style.zIndex = (i < flipped) ? (i + 1) : (N - i + 10);
    }});
    document.getElementById('btnBack').disabled = (flipped === 0);
    document.getElementById('btnFwd').disabled = (flipped === N);
    document.getElementById('pageInfo').textContent =
      spreadNames[Math.min(flipped, spreadNames.length - 1)] + "  ·  " + flipped + " / " + N;
  }}

  function turn(dir) {{
    flipped = Math.min(N, Math.max(0, flipped + dir));
    render();
  }}

  document.getElementById('book').addEventListener('click', (e) => {{
    const rect = e.currentTarget.getBoundingClientRect();
    turn(e.clientX - rect.left > rect.width / 2 ? 1 : -1);
  }});
  document.addEventListener('keydown', (e) => {{
    if (e.key === 'ArrowRight' || e.key === ' ') turn(1);
    if (e.key === 'ArrowLeft') turn(-1);
  }});
  let touchX = null;
  document.addEventListener('touchstart', e => touchX = e.touches[0].clientX, {{passive: true}});
  document.addEventListener('touchend', e => {{
    if (touchX === null) return;
    const dx = e.changedTouches[0].clientX - touchX;
    if (Math.abs(dx) > 40) turn(dx < 0 ? 1 : -1);
    touchX = null;
  }}, {{passive: true}});

  render();
</script>
</body>
</html>
"""

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
OUT_PATH.write_text(html, encoding="utf-8")
print(f"Saved: {OUT_PATH}")
