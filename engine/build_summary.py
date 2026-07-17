#!/usr/bin/env python3
"""
Abridged, single-scroll-page summary of the "Can SAM Be Improved?" case.

This is the short version: for SAM players and DEN admins who want the
headline in two minutes, not the full 30-page storybook. Same live data
pipeline as build_storybook.py (same computed figures, same source of
truth) -- just a much shorter, plain-language presentation with no
flip-book mechanic. Links out to the full storybook for anyone who wants
the underlying data, case studies, and methodology.

Sections: The Problem -> One Concrete Morning -> The Core Flaw ->
The Fix (Two Phases) -> Where to Learn More.
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
OUT_PATH = REPO_ROOT / "output" / "summary.html"

# ══ Load & prepare data (identical pipeline to build_storybook.py) ═══════════
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

first_year = raw["posted_dt"].min().year
latest = raw["posted_dt"].max().strftime("%B %-d, %Y")

print("Replaying rating history...")
player_log = build_full_player_log(raw)

print("Building exhibits...")
cb = build_competitive_balance_by_quarter(player_log)

lb = pd.read_excel(XLSX_PATH, sheet_name="Leaderboard")
n_active = len(lb)

print("Running court-assignment scenarios (90 days)...")
_, scenario_summary, _ = build_court_assignment_analysis(raw, player_log, days=90)

def scen(*needle_sets):
    for needles in needle_sets:
        if isinstance(needles, str):
            needles = (needles,)
        for _, row in scenario_summary.iterrows():
            name = str(row["Scenario"]).lower()
            if all(n.lower() in name for n in needles):
                return row
    return None

den = scen(("den", "current"), "den")
den_1u1b = scen(("den", "1u1b"))
ph1 = scen(("elo", "1u1b"))
ph2 = scen(("elo", "k100"))

def sv(row, key, default="—"):
    if row is None:
        return default
    v = row.get(key, default)
    return default if pd.isna(v) else v

cbq = cb.set_index("Quarter")
want = ["2022 Q1", "2023 Q1", "2024 Q1", "2025 Q2"]
show_q = [q for q in want if q in cbq.index]
_current_q = pd.Timestamp.now().to_period("Q")
_current_q_str = f"{_current_q.year} Q{_current_q.quarter}"
mature = cb[(cb["Games"] >= 60) & (cb["Quarter"] != _current_q_str)]
latest_q = mature["Quarter"].iloc[-1] if not mature.empty else cb["Quarter"].iloc[-1]
if latest_q not in show_q:
    show_q.append(latest_q)
show_q = [q for q in show_q if q <= latest_q or q in want]
q_first = cbq.loc[show_q[0]]
q_last = cbq.loc[show_q[-1]]

_gap_ratio = q_last["Avg Gap"] / q_first["Avg Gap"] if q_first["Avg Gap"] else 1
if 1.85 <= _gap_ratio <= 2.15:
    gap_uneven_phrase = "roughly <b>twice as uneven</b>"
elif _gap_ratio > 2.15:
    gap_uneven_phrase = f"roughly <b>{_gap_ratio:.1f}x as uneven</b>"
elif _gap_ratio >= 1.4:
    gap_uneven_phrase = f"roughly <b>{_gap_ratio:.1f}x as uneven</b>"
elif _gap_ratio > 1.05:
    gap_uneven_phrase = f"roughly <b>{round((_gap_ratio - 1) * 100)}% more uneven</b>"
elif _gap_ratio >= 0.95:
    gap_uneven_phrase = "<b>about as uneven</b>"
else:
    gap_uneven_phrase = f"roughly <b>{round((1 - _gap_ratio) * 100)}% less uneven</b>"

den_comb = sv(den, "Combined Spread")
den_move = sv(den, "S1→S2 % Moving")
den_s1 = sv(den, "S1 Avg Spread")
den_s2 = sv(den, "S2 Avg Spread")
den_1u1b_s2 = sv(den_1u1b, "S2 Avg Spread")
ph1_comb = sv(ph1, "Combined Spread")
ph2_comb = sv(ph2, "Combined Spread")
ph1_vs = sv(ph1, "vs DEN")
ph2_vs = sv(ph2, "vs DEN")

# ══ HTML ══════════════════════════════════════════════════════════════════════
html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Can SAM Be Improved? — The Short Version</title>
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
  body {{
    font-family: Georgia, 'Times New Roman', serif;
    background: var(--paper);
    color: var(--ink);
    line-height: 1.6;
  }}
  .wrap {{ max-width: 620px; margin: 0 auto; padding: 48px 24px 80px; }}
  header {{ text-align: center; margin-bottom: 48px; }}
  header .rule {{ width: 56px; height: 2px; background: var(--accent); margin: 0 auto 20px; }}
  header h1 {{ font-size: clamp(26px, 5vw, 38px); color: var(--navy); font-weight: normal; line-height: 1.2; margin-bottom: 8px; }}
  header .sub {{ font-family: 'Trebuchet MS', sans-serif; font-size: 13px; letter-spacing: 1.5px; text-transform: uppercase; color: var(--navy-2); }}

  section {{ margin-bottom: 48px; }}
  .kicker {{
    font-family: 'Trebuchet MS', Verdana, sans-serif;
    font-size: 11.5px; letter-spacing: 2.2px; text-transform: uppercase;
    color: var(--navy-2); margin-bottom: 10px;
  }}
  h2 {{ font-size: clamp(20px, 3.5vw, 26px); color: var(--navy); font-weight: normal; margin-bottom: 14px; line-height: 1.25; }}
  p {{ font-size: 16px; line-height: 1.65; margin-bottom: 14px; }}

  .stat-row {{ display: flex; gap: 12px; flex-wrap: wrap; margin: 20px 0; }}
  .stat {{ flex: 1; min-width: 140px; border-left: 4px solid var(--navy-2); background: var(--tan); padding: 16px 18px; border-radius: 0 8px 8px 0; }}
  .stat.flag {{ border-left-color: #b3543a; }}
  .stat .num {{ font-size: 28px; color: var(--navy); }}
  .stat .lbl {{ font-family: 'Trebuchet MS', sans-serif; font-size: 12px; color: #6d6353; margin-top: 3px; }}

  .callout {{
    padding: 18px 22px; background: var(--navy); color: #fff;
    border-radius: 8px; font-size: 15px; line-height: 1.55; margin: 18px 0;
  }}
  .callout b {{ color: var(--accent); }}

  .flaw {{ background: var(--tan); border-left: 4px solid #b3543a; border-radius: 0 8px 8px 0;
           padding: 14px 20px; margin-bottom: 12px; }}
  .flaw b {{ display: block; font-family: 'Trebuchet MS', sans-serif; color: #8a3c26; font-size: 12.5px; margin-bottom: 3px; }}

  .phase {{ background: var(--tan); border-radius: 10px; padding: 20px 24px; margin-bottom: 16px;
            border-top: 4px solid var(--accent); }}
  .phase b {{ display: block; font-family: 'Trebuchet MS', sans-serif; color: var(--navy); font-size: 15px; margin-bottom: 6px; }}
  .phase .metric {{ margin-top: 10px; font-family: 'Trebuchet MS', sans-serif; font-size: 12.5px; color: var(--navy-2); font-weight: bold; }}

  .divider {{ height: 1px; background: #e0d7c3; margin: 44px 0; }}

  footer {{
    text-align: center; background: linear-gradient(145deg, var(--navy) 0%, #16385a 100%);
    color: #fff; border-radius: 12px; padding: 36px 24px; margin-top: 20px;
  }}
  footer .rule {{ width: 56px; height: 2px; background: var(--accent); margin: 0 auto 18px; }}
  footer h3 {{ font-size: 20px; font-weight: normal; margin-bottom: 14px; }}
  footer p {{ font-size: 14px; color: #e8edf3; margin-bottom: 6px; }}
  footer a {{ color: var(--accent); text-decoration: none; font-size: 15px; }}
  footer .fine {{ font-size: 11px; opacity: 0.6; margin-top: 16px; }}
</style>
</head>
<body>
<div class="wrap">

  <header>
    <div class="rule"></div>
    <h1>Can SAM Be Improved?</h1>
    <div class="sub">The Short Version</div>
  </header>

  <section>
    <div class="kicker">The Problem</div>
    <h2>Games Have Gotten Less Competitive</h2>
    <p>SAM's player pool has grown a lot more diverse in skill over the past few years. Today's court matchups are {gap_uneven_phrase} as they were in early {first_year if first_year >= 2022 else 2022} &mdash; and Pickleball Den's built-in court-assignment system, Step and Percentage, wasn't built to sort a field this wide.</p>
  </section>

  <section>
    <div class="kicker">One Concrete Morning</div>
    <h2>June 17, 2026</h2>
    <div class="stat-row">
      <div class="stat"><div class="num">16</div><div class="lbl">players signed up</div></div>
      <div class="stat flag"><div class="num">13 of 16</div><div class="lbl">landed outside their correct skill tier</div></div>
    </div>
    <div class="callout">Pool 2 paired Peter Rillero and Eric Kramer &mdash; ranked #3 and #1 overall &mdash; with Donna Cantrell and Paul Batie, ranked #11 and #13. Rillero and Kramer won <b>11&ndash;4</b>, a 651-point average rating gap between the teams.</div>
    <p>This wasn't a one-off. It was the whole signup sheet, miscalibrated at once.</p>
  </section>

  <section>
    <div class="kicker">The Core Flaws</div>
    <h2>Two Structural Problems</h2>
    <p>Step is a court-movement counter, not a skill score &mdash; and it's blind to turnout. Reaching Pool 1 on a two-court day means beating half the field. On a five-court day, it means beating four-fifths of it. Step treats both accomplishments as identical.</p>
    <div class="flaw"><b>COURT-COUNT BLIND</b><span> &mdash; a step earned on a slow day and a step earned on a big day carry the same weight, even though one was a meaningfully harder result than the other.</span></div>
    <p>Worse: the shuffle SAM currently runs between sessions &mdash; DEN's &ldquo;2-up/2-back&rdquo; option &mdash; doesn't fix the miscalibration. We measured it directly: Session 1 courts average a {den_s1}-point internal skill spread; after 2-up/2-back moves the top two and bottom two on every court, that spread actually <b>widens</b> to {den_s2}. The rule meant to correct mismatches is mostly producing counterproductive movement instead.</p>
    <div class="flaw"><b>THE FIX IS ALREADY IN DEN</b><span> &mdash; switching to DEN's own gentler option, &ldquo;1-up/1-back/2-stay&rdquo; (moving one player per court instead of two), measurably improves competitiveness: {den_1u1b_s2}-point spread, using a setting DEN already has today, no new tooling required.</span></div>
  </section>

  <section>
    <div class="kicker">The Fix</div>
    <h2>Two Phases, Already Built and Tested</h2>
    <div class="phase">
      <b>PHASE 1 &mdash; Rating-seeded start, gentler shuffle</b>
      <span>Seed Session 1 by rating instead of step and percentage. No new DEN setting exists for this &mdash; it works by writing values into DEN's own Ladder Step field and letting DEN's own tools do the rest. Already tested live, start to finish.</span>
      <div class="metric">{ph1_vs} better-matched courts &middot; combined spread {ph1_comb}</div>
    </div>
    <div class="phase">
      <b>PHASE 2 &mdash; Results-driven Session 2</b>
      <span>Session 2 courts rebuilt from Session 1 results, weighted by opponent strength &mdash; movement is earned, not mechanical. Same technique, extended to Session 2.</span>
      <div class="metric">{ph2_vs} better-matched courts &middot; combined spread {ph2_comb}</div>
    </div>
    <p style="font-size:13px;color:#8a7f6a;">Today's baseline: {den_comb} combined spread, {den_move} of players moving mid-morning.</p>
  </section>

  <div class="divider"></div>

  <footer>
    <div class="rule"></div>
    <h3>Want the Full Case?</h3>
    <p>Every case study, every chart, and the full technical methodology<br>live in the complete storybook.</p>
    <p style="margin-top:16px;"><a href="storybook.html">Read the full storybook &rarr;</a></p>
    <p style="margin-top:10px;"><a href="https://billpollock1-hue.github.io/sam-pickleball/">Anthem SAM &middot; Live Results</a></p>
    <div class="fine">Data through {latest} &middot; {n_active} active leaderboard players</div>
  </footer>

</div>
</body>
</html>
"""

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
OUT_PATH.write_text(html, encoding="utf-8")
print(f"Saved: {OUT_PATH}")
