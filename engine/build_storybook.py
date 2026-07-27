#!/usr/bin/env python3
"""
Storybook presentation of the court-assignment case — an open-faced book
with 3D page turns. Self-contained HTML; all exhibits computed live from
the master history and the engine's own analysis functions, so the book
refreshes with every model run.

Spreads: Cover → Challenge → Metric → Proof → Opponent Blind → Evidence →
Root Cause → DEN System → 2-up/2-back → Options → Recommendation →
Technical Appendix (2 spreads) → Back cover.

OPPONENT-BLIND SPREAD (added): a dedicated 2-page spread inserted right
after the "Three Factors" page, making the opponent-strength argument its
own beat instead of a single line in the page-14 flaw list (that flaw box
is left in place for skimmers). Ties directly back to Elo's three factors
(result, margin, opponent strength) introduced on the facing page.

PAGE-PAIRING NOTE: the flip mechanic only ever shows (previous sheet's
back face) next to (current sheet's front face) at the same time -- a
single sheet's own front and back are NEVER visible together. Content
that needs to be read side-by-side (an exhibit and its narrative) must
therefore be split as back-of-sheet-N / front-of-sheet-(N+1), not as
front/back of the same sheet. The June 17 / May 4 / court-count-blind
exhibits were originally each a single sheet's own front+back, so their
narratives were never actually visible next to their charts. Fixed by
merging the June 17 exhibit onto one page (freeing exactly one page slot)
and reassigning every following page to the correct front/back slot so
each chart's back face lines up with its narrative's front face.
"""

import sys
from pathlib import Path

import numpy as np
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

# Pulled live from gap_dist (not hardcoded) so the callout and technical
# appendix mentions of these percentages can never drift from the table
# itself -- previously "78%" was a typed-in string that fell out of sync
# as more games accumulated and the real figure moved to 79.4%.
_gap_pcts = dict(zip(
    gap_dist["Rating Gap"],
    gap_dist["% Won by Higher-Rated Team"].str.rstrip("%").astype(float),
))
pct_0_100   = round(_gap_pcts.get("0–100", 0))
pct_101_200 = round(_gap_pcts.get("101–200", 0))
pct_201_300 = round(_gap_pcts.get("201–300", 0))
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

# Competitive balance display quarters: first, latest MEANINGFUL, waypoints.
# The current in-progress quarter can have only a handful of play dates —
# too thin a sample to anchor trend claims — so require a real game count.
cbq = cb.set_index("Quarter")
want = ["2022 Q1", "2023 Q1", "2024 Q1", "2025 Q2"]
show_q = [q for q in want if q in cbq.index]
# The current in-progress calendar quarter must never be treated as
# "mature" for trend claims, no matter how many games it has already
# accumulated -- a fast-playing group can clear a game-count threshold
# within days of a new quarter starting, long before the quarter is
# actually representative of anything.
_current_q = pd.Timestamp.now().to_period("Q")
_current_q_str = f"{_current_q.year} Q{_current_q.quarter}"
mature = cb[(cb["Games"] >= 60) & (cb["Quarter"] != _current_q_str)]
latest_q = mature["Quarter"].iloc[-1] if not mature.empty else cb["Quarter"].iloc[-1]
if latest_q not in show_q:
    show_q.append(latest_q)
show_q = [q for q in show_q if q <= latest_q or q in want]
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
        <td><div class="bar"><div class="track"><span style="width:{barw}%;"></span></div><em>{round(r['Avg Gap'])}</em></div></td>
        <td>{round(100 * r['% Under 200'])}%</td>
      </tr>"""

gap_rows = ""
for _, r in gap_dist.iterrows():
    gap_rows += f"""
      <tr><td>{r['Rating Gap']}</td><td>{r['% Won by Higher-Rated Team']}</td>
      <td>{r.get('Margin 1–3','—')}</td><td>{r.get('Margin 9–11','—')}</td></tr>"""

# Effort labels corrected 2026-07-21: "Settings only" wrongly implied
# Rating-seeded scenarios need no automation at all, when they in fact
# depend on the same rating engine as everything else here -- the real
# distinction is whether that automation already exists and runs
# unattended (Rating-seeded start, via the already-built/validated
# pipeline) versus needs to be newly built and triggered live on-site
# in the tight post-Shootout-1 window (everything results-driven).
options = [
    ("Rating-seeded start &middot; keep today's shuffle", sv(e2u, "vs DEN"), sv(e2u, "S1→S2 % Moving"), "Already automated"),
    ("Rating-seeded start &middot; gentler shuffle &nbsp;&#9733; Phase 1", sv(ph1, "vs DEN"), sv(ph1, "S1→S2 % Moving"), "Already automated"),
    ("Results-driven Shootout 2 &middot; steady dial", sv(e20, "vs DEN"), sv(e20, "S1→S2 % Moving"), "New automation"),
    ("Results-driven Shootout 2 &middot; balanced dial &nbsp;&#9733; Phase 2", sv(ph2, "vs DEN"), sv(ph2, "S1→S2 % Moving"), "New automation"),
    ("Results-driven Shootout 2 &middot; fast dial", sv(k150, "vs DEN"), sv(k150, "S1→S2 % Moving"), "New automation"),
    ("Swap near-ties at court borders only", sv(bsw, "vs DEN"), sv(bsw, "S1→S2 % Moving"), "New automation"),
    ("Move only big over/under-performers", sv(upt, "vs DEN"), sv(upt, "S1→S2 % Moving"), "New automation"),
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

# Trendline-based (added 2026-07-21), same reasoning and method as the
# Avg Gap fix below: a raw first-vs-last QUARTER comparison is oversensitive
# to whichever single quarter happens to anchor each end. Fit each series
# across the full quarterly history and report the fitted endpoints instead
# of the raw ones.
_trend_x = np.arange(len(cb))


def _trend_endpoints(col):
    y = cb[col].values
    slope, intercept = np.polyfit(_trend_x, y, 1)
    fitted = slope * _trend_x + intercept
    return fitted[0], fitted[-1]

_lt200_first, _lt200_last = _trend_endpoints("% Under 200")
pct_lt200_first = round(100 * _lt200_first)
pct_lt200_last = round(100 * _lt200_last)

_close_first, _close_last = _trend_endpoints("% Decided by <=3")
pct_close_first = round(100 * _close_first)
pct_close_last = round(100 * _close_last)

_blowout_first, _blowout_last = _trend_endpoints("% Decided by 9+")
pct_blowout_first = round(100 * _blowout_first)
pct_blowout_last = round(100 * _blowout_last)

# Trendline replaces the earlier first-vs-last QUARTER point comparison
# (added 2026-07-21): that comparison overstated apparent growth because
# the first quarter shown (2022 Q1) happens to sit almost at the lowest
# single value in the entire quarterly series (2022 Q2 is barely lower).
# A least-squares fit across the FULL series is far less sensitive to any
# one noisy quarter at either end, and is the same approach discussed
# (but never implemented) in the 2026-07-20 session.
_trend_x = np.arange(len(cb))
_trend_y = cb["Avg Gap"].values
_slope, _intercept = np.polyfit(_trend_x, _trend_y, 1)
_fitted = _slope * _trend_x + _intercept
_ss_res = ((_trend_y - _fitted) ** 2).sum()
_ss_tot = ((_trend_y - _trend_y.mean()) ** 2).sum()
_r_squared = (1 - (_ss_res / _ss_tot)) if _ss_tot else 0
_gap_ratio = (_fitted[-1] / _fitted[0]) if _fitted[0] else 1


def build_gap_trend_svg(cb, slope, intercept, r_squared):
    """Scatter of the real per-quarter Avg Gap values with the fitted
    least-squares trendline drawn through them -- added 2026-07-21 to
    replace a 5-row waypoint table + bare ratio callout that asserted a
    trend number without letting the reader see it. Shows genuine
    quarter-to-quarter noise (2022 Q1 low, 2024 Q1 spike, etc.) alongside
    the steady underlying climb, plus R-squared so the strength of the
    fit is stated honestly rather than implied."""
    n = len(cb)
    y_vals = cb["Avg Gap"].values
    x_left, x_right = 45, 400
    y_top, y_bottom = 25, 205
    y_min, y_max = 100, 250

    def xp(i):
        return x_left + i * (x_right - x_left) / (n - 1)

    def yp(v):
        return y_bottom - (v - y_min) / (y_max - y_min) * (y_bottom - y_top)

    parts = []
    for gv in (100, 150, 200, 250):
        gy = yp(gv)
        parts.append(f'<line x1="{x_left}" y1="{gy}" x2="{x_right}" y2="{gy}" stroke="#d8cfba" stroke-width="0.75"/>')
        parts.append(f'<text x="{x_left - 6}" y="{gy + 3}" text-anchor="end" font-family="\'Trebuchet MS\',sans-serif" font-size="8" fill="#8a7f6a">{gv}</text>')

    fitted_x0, fitted_x1 = 0, n - 1
    fitted_y0 = slope * fitted_x0 + intercept
    fitted_y1 = slope * fitted_x1 + intercept
    parts.append(f'<line x1="{xp(fitted_x0)}" y1="{yp(fitted_y0)}" x2="{xp(fitted_x1)}" y2="{yp(fitted_y1)}" stroke="#b3543a" stroke-width="2"/>')

    for i, v in enumerate(y_vals):
        parts.append(f'<circle cx="{xp(i)}" cy="{yp(v)}" r="2.5" fill="var(--navy)"/>')

    label_idxs = list(range(0, n, 4))
    if label_idxs[-1] != n - 1:
        label_idxs.append(n - 1)
    for i in label_idxs:
        q = cb["Quarter"].iloc[i]
        parts.append(f'<text x="{xp(i)}" y="{y_bottom + 14}" text-anchor="middle" font-family="\'Trebuchet MS\',sans-serif" font-size="7.5" fill="var(--ink)">{q}</text>')

    parts.append(f'<text x="{x_right}" y="18" text-anchor="end" font-family="\'Trebuchet MS\',sans-serif" font-size="8.5" font-style="italic" fill="#8a7f6a">R&sup2; = {r_squared:.2f}</text>')

    body = "\n          ".join(parts)
    return f'<svg viewBox="0 0 420 230" width="100%" style="display:block;">\n          {body}\n        </svg>'


gap_trend_svg = build_gap_trend_svg(cb, _slope, _intercept, _r_squared)

if _gap_ratio >= 1.85:
    gap_change_phrase = "has nearly doubled"
elif _gap_ratio >= 1.4:
    gap_change_phrase = f"has grown to roughly {_gap_ratio:.1f}x"
elif _gap_ratio > 1.05:
    gap_change_phrase = f"has grown by {round((_gap_ratio - 1) * 100)}%"
elif _gap_ratio >= 0.95:
    gap_change_phrase = "has stayed roughly flat"
else:
    gap_change_phrase = f"has fallen by {round((1 - _gap_ratio) * 100)}%"

# Separate phrase for the standalone "twice as uneven" callout -- narrower
# band (1.85-2.15) required specifically for "roughly twice" per Bill's
# preference, since that's a much more specific claim than "nearly doubled"
# and shouldn't be used loosely across a wide ratio range.
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

# ══ HTML ══════════════════════════════════════════════════════════════════════
html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Can SAM Be Improved?</title>
<style>
  :root {{
    --navy: #1e3a5f; --navy-2: #2c5282; --tan: #f4ecd8; --ink: #2d2a26;
    --paper: #fdf9f0; --accent: #c9a44c;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; font-family: 'Georgia', 'Times New Roman', serif;
    background: var(--paper); color: var(--ink); line-height: 1.65;
  }}
  .doc-wrap {{ max-width: 720px; margin: 0 auto; padding: 40px 24px 100px; }}
  .section {{ padding: 20px 0; }}
  .cover-section {{ text-align: center; padding: 60px 0; }}
  .cover-section h1 {{ font-size: clamp(28px, 5vw, 44px); color: var(--navy); font-weight: normal; }}
  .cover-section .rule {{ width: 60px; height: 2px; background: var(--accent); margin: 16px auto; }}
  .cover-section .sub {{ font-size: 16px; color: #6b6355; margin-top: 12px; }}
  .cover-section .hint {{ display: none; }}
  .back-cover-section {{
    background: var(--navy); color: #fff; text-align: center; padding: 60px 24px;
    margin: 40px -24px 0; border-radius: 8px;
  }}
  .back-cover-section h1 {{ font-weight: normal; font-size: 28px; }}
  .back-cover-section a {{ color: var(--accent); }}
  .back-cover-section .rule {{ width: 56px; height: 2px; background: var(--accent); margin: 0 auto 20px; }}
  .kicker {{
    font-family: 'Trebuchet MS', sans-serif; font-size: 12px; letter-spacing: 2px;
    text-transform: uppercase; color: var(--navy-2); font-weight: bold; margin-bottom: 8px;
  }}
  h2 {{ color: var(--navy); font-weight: normal; font-size: 26px; margin: 8px 0 20px; }}
  p {{ margin: 0 0 16px; font-size: 17px; }}
  .factor {{ margin: 0 0 14px; }}
  .factor b {{ color: var(--navy); margin-right: 6px; }}
  .flaw {{ margin: 0 0 14px; }}
  .flaw b {{ color: #b3543a; margin-right: 6px; }}
  .callout {{
    background: var(--navy); color: #fff; padding: 20px 24px; border-radius: 8px; margin: 20px 0;
  }}
  .stat-stack {{ display: flex; flex-direction: column; gap: 16px; margin: 20px 0; }}
  .stat {{ border-left: 3px solid var(--navy-2); padding-left: 16px; }}
  .stat .num {{ font-size: 32px; color: var(--navy); }}
  .stat .lbl {{ font-size: 14px; color: #6b6355; }}
  table.btable, table.ps-table {{ width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 15px; }}
  table.btable th, table.ps-table th {{ background: var(--navy-2); color: #fff; padding: 8px 10px; text-align: left; }}
  table.btable td, table.ps-table td {{ padding: 8px 10px; border-bottom: 1px solid #e5ddc8; }}
  .pgnum {{ display: none; }}
  svg {{ max-width: 100%; height: auto; display: block; margin: 20px auto; }}
  .mono {{ font-family: monospace; font-size: 13px; color: #8a7f6a; margin-top: 16px; }}

</style>
</head>
<body>
<div class="doc-wrap">
<div class="section cover-section">

<div class="rule"></div>
<h1>Can SAM<br/>Be Improved?</h1>
<div class="rule"></div>
<div class="sub">Using four years of shootout data to make<br/>every SAM session more competitive</div>
<div class="sub" style="font-size:0.65em;opacity:0.65;margin-top:2%;">Snapshot as of July 21, 2026 — numbers reflect data through this date, not live</div>
<div class="hint">click to open ›</div>

</div>

<div class="section">

<div class="kicker">Chapter One</div>
<h2>The Challenge: From Perception to Evidence</h2>
<p>Players in the SAM shootout have raised concerns about court competitiveness — too many lopsided games, courts that feel mismatched.</p>
<p>Perception is a starting point, but it is not enough to diagnose the problem or evaluate solutions. We need an objective metric: a way to measure the skill gap between teams in any given game, consistently, across thousands of games and multiple years.</p>
<p>Fortunately, we have exactly the raw material that requires: the historical SAM shootout data from Pickleball Den.</p>
<div class="pgnum">1</div>

</div>

<div class="section">

<div class="kicker">The Raw Material</div>
<div class="stat-stack">
<div class="stat"><div class="num">{n_games:,}</div><div class="lbl">games recorded since {first_year}</div></div>
<div class="stat"><div class="num">{n_dates:,}</div><div class="lbl">play dates captured</div></div>
<div class="stat"><div class="num">{n_all_players}</div><div class="lbl">players who have taken the court</div></div>
</div>
<div class="pgnum">2</div>

</div>

<div class="section">

<div class="kicker">Chapter Two</div>
<h2>The Metric: Modified Elo</h2>
<p>Elo is a rating system originally developed for chess and widely used in competitive sports. Every player starts at 1,000. After each game, all four players’ ratings update based on the result versus what the model predicted.</p>
<p>Your team’s rating is the average of you and your partner. The bigger the rating gap between two teams, the more confidently the model expects the stronger side to win.</p>
<p>One club-specific adjustment, covered in the appendix, helps new players converge to an accurate rating quickly.</p>
<div class="pgnum">3</div>

</div>

<div class="section">

<div class="kicker">Three Factors Drive Every Update</div>
<div class="factor"><b>1 · RESULT</b><span>Winning earns points; losing costs points.</span></div>
<div class="factor"><b>2 · MARGIN</b><span>An 11–2 win moves ratings more than an 11–9 win.</span></div>
<div class="factor"><b>3 · OPPONENT STRENGTH</b><span>Beating a strong team earns more than beating a weak one.</span></div>
<div class="callout">In observed SAM games, the higher-rated team wins <b>{pct_0_100}%</b> of games with a gap under 100 points, <b>{pct_101_200}%</b> in the 101–200 range, and <b>{pct_201_300}%</b> in the 201–300 range.</div>
<div class="pgnum">4</div>

</div>

<div class="section">

<div class="kicker">Chapter Three</div>
<h2>Are Our Modified Elo Ratings Accurate?</h2>
<p>A rating is only useful if it predicts real outcomes. So before drawing any conclusions, we checked the model against every rated game in the dataset.</p>
<p>The pattern is exactly what a healthy rating system should show: the bigger the pre-game rating gap between two teams, the more often the favorite wins — and the more lopsided the score gets.</p>
<p>Small gaps produce coin-flip games decided by just a few points. Big gaps produce blowouts. The facing page shows the full relationship.</p>
<div class="pgnum">5</div>

</div>

<div class="section">

<div class="kicker">Chapter Two, Continued</div>
<h2>Three Factors vs. One and a Half</h2>
<p>Elo’s three inputs — result, margin, opponent strength — aren’t optional extras. Opponent strength is the one that makes a rating mean anything: beat a strong team and you earn more; lose to one and you lose less. Without it, a win is just a win, with no sense of how hard it was.</p>
<p>Pickleball Den’s court assignment metrics, Step and Percentage, never make that adjustment. Step is set from a player’s last Shootout 2 finish: top two on a court moves them toward the top court next time, bottom two moves them toward the bottom — based purely on finishing position. Picture two players on the same date: one finishes bottom-two on the toughest court and moves toward a worse court next time; another finishes top-two on the weakest court and moves toward a better court next time. Both land on the same Step for the next Shootout 1 — despite one facing that day’s toughest competition and the other its weakest. Percentage, the tiebreaker when Steps match, doesn’t fix this either: it’s just total points scored over a player’s last 90 games, with no adjustment for who those points came against.</p>
<div class="callout">Elo asks three questions of every result: did you win, by how much, and against whom. DEN’s system fully answers the first and only partially answers the second — Percentage counts total points, not points earned against strong or weak competition — and skips the third entirely: the one that actually tells you how much a result should count.</div>
<div class="pgnum">6</div>

</div>

<div class="section">

<div class="kicker">Chapter Two, Continued</div>
<h2>Same Morning, Same Record, Different Reality</h2>
<p>This isn’t a hypothetical — it plays out constantly. Two players can each finish bottom-two on the same-numbered court, on different play dates, and land on the identical Step for their next Shootout 1 — even though one faced a much tougher field that day than the other did.</p>
<p>Elo would separate them sharply: losing to strong competition is expected and costs the first player’s rating very little, while the same finish against a weaker field is a real signal and costs the second player’s rating meaningfully more. Step is simplistic — both players get the same step change, based purely on top-two/bottom-two finish, with no memory of who was actually across the net.</p>
<p>The result compounds every time it happens: players who consistently face tougher competition get systematically under-credited, while players who consistently face weaker competition get systematically over-credited — and neither shows up anywhere in Step or Percentage.</p>
<div class="pgnum">7</div>

</div>

<div class="section">

<div class="kicker">Rating Gap vs. Real Outcomes</div>
<table class="btable">
<tr><th>Team Rating Gap</th><th>Favorite Wins</th><th>Decided by 1–3 pts</th><th>Decided by 9–11 pts</th></tr>
          {gap_rows}
        </table>
<p style="font-size:clamp(8.5px,1vw,12px);color:#8a7f6a;margin-top:3%;">All rated games, {first_year}–present. Close games fade and blowouts grow as the gap widens.</p>
<div class="pgnum">8</div>

</div>

<div class="section">

<div class="kicker">Chapter Four</div>
<h2>The Evidence: A Growing Competitiveness Problem</h2>
<p>With a trustworthy measuring stick, we can now measure match quality directly. “Match gap” is the rating difference between the two teams in a game — smaller means more evenly matched.</p>
<p>The trend is unmistakable. The average match gap {gap_change_phrase} since early {first_year + 0 if first_year >= 2022 else 2022}, and games that qualify as closely matched — a gap under 200 points — have fallen from {pct_lt200_first}% of all games to {pct_lt200_last}%.</p>
<p>Raw scores tell a quieter version of the same story: games decided by 3 points or less have {'fallen' if pct_close_last <= pct_close_first else 'risen'} from {pct_close_first}% to {pct_close_last}% of all matches, while blowouts (9+ points) have {'risen' if pct_blowout_last >= pct_blowout_first else 'fallen'} from {pct_blowout_first}% to {pct_blowout_last}%.</p>
<p>Mismatched games are no longer rare exceptions. They are now the norm for roughly 4 in 10 matches.</p>
<div class="pgnum">9</div>

</div>

<div class="section">

<div class="kicker">Average Match Gap by Quarter</div>
<div style="font-family:'Trebuchet MS',sans-serif;font-size:clamp(8.5px,1vw,11px);color:var(--navy);font-weight:bold;text-align:center;margin-bottom:2%;">Average match rating gap, by quarter</div>
        {gap_trend_svg}
        <div class="callout" style="margin-top:5%;">The trendline shows the average match gap growing steadily — {gap_uneven_phrase} today as it was in early {first_year if first_year >= 2022 else 2022} — despite real quarter-to-quarter noise.</div>
<div class="pgnum">10</div>

</div>

<div class="section">

<div class="kicker">Chapter Five</div>
<h2>The Root Cause: A Wider Player Pool</h2>
<p>The driver is not a shortage of strong players — it is that the SAM player pool has grown dramatically more diverse in skill.</p>
<p>Today’s leaderboard spans {n_active} active players — those with at least 24 rated games played within the past 180 days. The rating spread across that group is {lb_range:,} points, top to bottom.</p>
<p>At that dispersion, the strongest player would be expected to beat the bottom of the leaderboard well over 99% of the time. Placing 12–20 players of this range onto 3–5 courts is genuinely hard — and the current assignment method wasn’t built for it.</p>
<div class="pgnum">11</div>

</div>

<div class="section">

<div class="kicker">Then vs. Now</div>
<div class="stat-stack">
<div class="stat"><div class="num">{round(q_first['Avg Gap'])} → {round(q_last['Avg Gap'])}</div><div class="lbl">average match gap, {show_q[0]} vs. {show_q[-1]}</div></div>
<div class="stat"><div class="num">~26 → {n_active}</div><div class="lbl">active leaderboard players</div></div>
<div class="stat"><div class="num">{lb_range:,} pts</div><div class="lbl">rating spread across today's leaderboard</div></div>
</div>
<div class="pgnum">12</div>

</div>

<div class="section">

<div class="kicker">Chapter Six</div>
<h2>How Courts Are Assigned Today</h2>
<p>The DEN makes Shootout 1 court assignments using two numbers. <b>Step</b> is a court-movement counter: finish in the top two of your court and it ticks down; finish in the bottom two and it ticks up — based entirely on your <i>last</i> play date, however long ago that was.</p>
<p><b>Percentage</b> breaks ties within a step: total points scored divided by maximum possible, over your last 90 games (~15 play dates), all weighted equally.</p>
<p>For Shootout 2, SAM currently has the DEN set to move the top two on each court up a court and the bottom two down — the “2-up/2-back” rule. It’s a choice, not the only option: the DEN also offers “1-up/1-back/2-stay,” which SAM isn’t currently using.</p>
<div style="margin-top:4%;">
<div style="font-family:'Trebuchet MS',sans-serif;font-size:clamp(8.5px,1vw,11px);color:var(--navy);font-weight:bold;text-align:center;margin-bottom:2%;">Step values in circulation after Shootout 2, by court count</div>
<svg style="display:block;" viewbox="0 0 420 230" width="100%">
<text fill="var(--navy)" font-family="'Trebuchet MS',sans-serif" font-size="10" font-weight="bold" text-anchor="middle" x="60" y="14">2 courts</text>
<rect fill="var(--navy-2)" height="42" rx="2" width="12" x="39" y="128"></rect>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="45" y="122">4</text>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="45" y="186">1</text>
<rect fill="#b3543a" height="21" rx="2" width="12" x="54" y="149"></rect>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="60" y="143">2</text>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="60" y="186">2</text>
<rect fill="#b3543a" height="21" rx="2" width="12" x="69" y="149"></rect>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="75" y="143">2</text>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="75" y="186">3</text>
<text fill="#8a7f6a" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="60" y="204">3 step values</text>
<text fill="var(--navy)" font-family="'Trebuchet MS',sans-serif" font-size="9.5" font-weight="bold" text-anchor="middle" x="60" y="68">avg step 1.75</text>
<text fill="var(--navy)" font-family="'Trebuchet MS',sans-serif" font-size="10" font-weight="bold" text-anchor="middle" x="160" y="14">3 courts</text>
<rect fill="var(--navy-2)" height="42" rx="2" width="12" x="131.5" y="128"></rect>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="137.5" y="122">4</text>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="137.5" y="186">1</text>
<rect fill="var(--navy-2)" height="42" rx="2" width="12" x="146.5" y="128"></rect>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="152.5" y="122">4</text>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="152.5" y="186">2</text>
<rect fill="#b3543a" height="21" rx="2" width="12" x="161.5" y="149"></rect>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="167.5" y="143">2</text>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="167.5" y="186">3</text>
<rect fill="#b3543a" height="21" rx="2" width="12" x="176.5" y="149"></rect>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="182.5" y="143">2</text>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="182.5" y="186">4</text>
<text fill="#8a7f6a" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="160" y="204">4 step values</text>
<text fill="var(--navy)" font-family="'Trebuchet MS',sans-serif" font-size="9.5" font-weight="bold" text-anchor="middle" x="160" y="68">avg step 2.17</text>
<text fill="var(--navy)" font-family="'Trebuchet MS',sans-serif" font-size="10" font-weight="bold" text-anchor="middle" x="260" y="14">4 courts</text>
<rect fill="var(--navy-2)" height="42" rx="2" width="12" x="224" y="128"></rect>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="230" y="122">4</text>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="230" y="186">1</text>
<rect fill="var(--navy-2)" height="42" rx="2" width="12" x="239" y="128"></rect>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="245" y="122">4</text>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="245" y="186">2</text>
<rect fill="var(--navy-2)" height="42" rx="2" width="12" x="254" y="128"></rect>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="260" y="122">4</text>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="260" y="186">3</text>
<rect fill="#b3543a" height="21" rx="2" width="12" x="269" y="149"></rect>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="275" y="143">2</text>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="275" y="186">4</text>
<rect fill="#b3543a" height="21" rx="2" width="12" x="284" y="149"></rect>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="290" y="143">2</text>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="290" y="186">5</text>
<text fill="#8a7f6a" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="260" y="204">5 step values</text>
<text fill="var(--navy)" font-family="'Trebuchet MS',sans-serif" font-size="9.5" font-weight="bold" text-anchor="middle" x="260" y="68">avg step 2.63</text>
<text fill="var(--navy)" font-family="'Trebuchet MS',sans-serif" font-size="10" font-weight="bold" text-anchor="middle" x="360" y="14">5 courts</text>
<rect fill="var(--navy-2)" height="42" rx="2" width="12" x="316.5" y="128"></rect>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="322.5" y="122">4</text>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="322.5" y="186">1</text>
<rect fill="var(--navy-2)" height="42" rx="2" width="12" x="331.5" y="128"></rect>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="337.5" y="122">4</text>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="337.5" y="186">2</text>
<rect fill="var(--navy-2)" height="42" rx="2" width="12" x="346.5" y="128"></rect>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="352.5" y="122">4</text>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="352.5" y="186">3</text>
<rect fill="var(--navy-2)" height="42" rx="2" width="12" x="361.5" y="128"></rect>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="367.5" y="122">4</text>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="367.5" y="186">4</text>
<rect fill="#b3543a" height="21" rx="2" width="12" x="376.5" y="149"></rect>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="382.5" y="143">2</text>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="382.5" y="186">5</text>
<rect fill="#b3543a" height="21" rx="2" width="12" x="391.5" y="149"></rect>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="397.5" y="143">2</text>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="397.5" y="186">6</text>
<text fill="#8a7f6a" font-family="'Trebuchet MS',sans-serif" font-size="8.5" text-anchor="middle" x="360" y="204">6 step values</text>
<text fill="var(--navy)" font-family="'Trebuchet MS',sans-serif" font-size="9.5" font-weight="bold" text-anchor="middle" x="360" y="68">avg step 3.10</text>
</svg>
<div style="font-family:'Trebuchet MS',sans-serif;font-size:clamp(7.5px,0.85vw,9.5px);color:#8a7f6a;text-align:center;margin-top:1%;">Players per step (top) · step number (bottom). More courts means more step values — and a higher average step — in play.</div>
</div>
<div class="pgnum">13</div>

</div>

<div class="section">

<div class="kicker">Structural Weaknesses</div>
<div class="flaw"><b>SINGLE-EVENT MEMORY</b><span>Step is always tied to one event — the second shootout of your last session — not any broader track record.</span></div>
<div class="flaw"><b>COURT-COUNT BLIND</b><span>A step earned on a 5-court day can penalize you when your next match is on a 3-court day. High-turnout days systematically punish; low-turnout days reward.</span></div>
<div class="flaw"><b>OPPONENT BLIND</b><span>A tough loss to the strongest players and an easy win over the weakest can land you on the same Step. Points scored are never adjusted for who you played or partnered with.</span></div>
<div class="flaw"><b>NO RECENCY REQUIREMENT</b><span>The step factor can be derived from a shootout that took place yesterday or three months ago.</span></div>
<div class="pgnum">14</div>

</div>

<div class="section">

<div class="kicker">Chapter Seven</div>
<h2>Not All Step 1s Are Equal</h2>
<p>On a two-court day, starting on Court 1 means finishing in the top half of eight players. On a three-court day, it means the top third of twelve. On a five-court day, it means the top fifth of twenty — a genuinely higher bar.</p>
<p>Step doesn’t know the difference. A step earned on Court 1 on a slow, low-turnout day carries the same weight as one earned on Court 1 on a big, high-turnout day, even though the second is a meaningfully harder accomplishment.</p>
<p>The same blindness runs the other direction too: falling to the bottom court on a big day assigns a higher step number outright than falling to the bottom court on a small day ever can, even though both are the same relative result — last place on the court. That gap only closes at your next play date, once a fresh top-two or bottom-two finish moves the counter again.</p>
<div class="pgnum">15</div>

</div>

<div class="section">

<div class="kicker">Chapter Seven, continued</div>
<p>We replayed the last 90 days of actual sessions and measured the skill spread inside each court — lower means the four players on a court are more evenly matched.</p>
<p>Under the current system, courts average a {den_s1}-point rating spread in Shootout 1. </p>
<div class="pgnum">16</div>

</div>

<div class="section">

<div class="kicker">Chapter Seven, Continued — Case Study, April 2, 2026</div>
<p>April 2, 2026 was a three-court day in SAM. The DEN’s court assignments were a mess.</p>
<svg style="display:block;" viewbox="0 0 420 500" width="100%">
<text fill="var(--navy)" font-family="'Trebuchet MS',sans-serif" font-size="12" font-weight="bold" text-anchor="middle" x="135" y="14">True rank before S1</text>
<text fill="var(--navy)" font-family="'Trebuchet MS',sans-serif" font-size="12" font-weight="bold" text-anchor="middle" x="340" y="14">Shootout 1 courts</text>
<rect fill="var(--tan)" height="140" rx="6" stroke="var(--navy-2)" stroke-width="0.75" width="140" x="270" y="26"></rect>
<text fill="var(--navy)" font-family="'Trebuchet MS',sans-serif" font-size="11" font-weight="bold" x="280" y="42">Court 1</text>
<rect fill="var(--tan)" height="140" rx="6" stroke="var(--navy-2)" stroke-width="0.75" width="140" x="270" y="181"></rect>
<text fill="var(--navy)" font-family="'Trebuchet MS',sans-serif" font-size="11" font-weight="bold" x="280" y="197">Court 2</text>
<rect fill="var(--tan)" height="140" rx="6" stroke="var(--navy-2)" stroke-width="0.75" width="140" x="270" y="336"></rect>
<text fill="var(--navy)" font-family="'Trebuchet MS',sans-serif" font-size="11" font-weight="bold" x="280" y="352">Court 3</text>
<line stroke="#E8871E" stroke-width="2" x1="135" x2="290" y1="30" y2="275"></line>
<line stroke="#E8871E" stroke-width="2" x1="135" x2="290" y1="70" y2="307"></line>
<line stroke="#b3543a" stroke-width="2.25" x1="135" x2="290" y1="110" y2="462"></line>
<line stroke="#E8871E" stroke-width="2" x1="135" x2="290" y1="150" y2="211"></line>
<line stroke="#E8871E" stroke-width="2" x1="135" x2="290" y1="190" y2="366"></line>
<line stroke="#E8871E" stroke-width="2" x1="135" x2="290" y1="230" y2="120"></line>
<line stroke="#E8871E" stroke-width="2" x1="135" x2="290" y1="270" y2="56"></line>
<line stroke="#E8871E" stroke-width="2" x1="135" x2="290" y1="310" y2="88"></line>
<line stroke="#b3543a" stroke-width="2.25" x1="135" x2="290" y1="350" y2="152"></line>
<line stroke="#1E8449" stroke-width="1.5" x1="135" x2="290" y1="390" y2="430"></line>
<line stroke="#1E8449" stroke-width="1.5" x1="135" x2="290" y1="430" y2="398"></line>
<line stroke="#E8871E" stroke-width="2" x1="135" x2="290" y1="470" y2="243"></line>
<text dominant-baseline="central" fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="11" text-anchor="end" x="125" y="30">L. Zolnierczyk</text>
<text dominant-baseline="central" fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="11" text-anchor="end" x="125" y="70">B. Pollock</text>
<text dominant-baseline="central" fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="11" text-anchor="end" x="125" y="110">A. Nagyova</text>
<text dominant-baseline="central" fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="11" text-anchor="end" x="125" y="150">C. McCormick</text>
<text dominant-baseline="central" fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="11" text-anchor="end" x="125" y="190">D. Grubb</text>
<text dominant-baseline="central" fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="11" text-anchor="end" x="125" y="230">T. Orr</text>
<text dominant-baseline="central" fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="11" text-anchor="end" x="125" y="270">P. Barnett</text>
<text dominant-baseline="central" fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="11" text-anchor="end" x="125" y="310">G. Egli</text>
<text dominant-baseline="central" fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="11" text-anchor="end" x="125" y="350">J. Milberg</text>
<text dominant-baseline="central" fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="11" text-anchor="end" x="125" y="390">W. Carroll</text>
<text dominant-baseline="central" fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="11" text-anchor="end" x="125" y="430">D. Witulski</text>
<text dominant-baseline="central" fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="11" text-anchor="end" x="125" y="470">J. Peterson</text>
<circle cx="135" cy="30" fill="var(--navy)" r="2.5"></circle>
<circle cx="135" cy="70" fill="var(--navy)" r="2.5"></circle>
<circle cx="135" cy="110" fill="var(--navy)" r="2.5"></circle>
<circle cx="135" cy="150" fill="var(--navy)" r="2.5"></circle>
<circle cx="135" cy="190" fill="var(--navy)" r="2.5"></circle>
<circle cx="135" cy="230" fill="var(--navy)" r="2.5"></circle>
<circle cx="135" cy="270" fill="var(--navy)" r="2.5"></circle>
<circle cx="135" cy="310" fill="var(--navy)" r="2.5"></circle>
<circle cx="135" cy="350" fill="var(--navy)" r="2.5"></circle>
<circle cx="135" cy="390" fill="var(--navy)" r="2.5"></circle>
<circle cx="135" cy="430" fill="var(--navy)" r="2.5"></circle>
<circle cx="135" cy="470" fill="var(--navy)" r="2.5"></circle>
<circle cx="290" cy="56" fill="var(--navy)" r="2.5"></circle>
<circle cx="290" cy="88" fill="var(--navy)" r="2.5"></circle>
<circle cx="290" cy="120" fill="var(--navy)" r="2.5"></circle>
<circle cx="290" cy="152" fill="var(--navy)" r="2.5"></circle>
<circle cx="290" cy="211" fill="var(--navy)" r="2.5"></circle>
<circle cx="290" cy="243" fill="var(--navy)" r="2.5"></circle>
<circle cx="290" cy="275" fill="var(--navy)" r="2.5"></circle>
<circle cx="290" cy="307" fill="var(--navy)" r="2.5"></circle>
<circle cx="290" cy="366" fill="var(--navy)" r="2.5"></circle>
<circle cx="290" cy="398" fill="var(--navy)" r="2.5"></circle>
<circle cx="290" cy="430" fill="var(--navy)" r="2.5"></circle>
<circle cx="290" cy="462" fill="var(--navy)" r="2.5"></circle>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="10.5" text-anchor="middle" x="210" y="488">Green: matched · Amber: 1 tier off · Red: 2 tiers off</text>
</svg>
<div class="pgnum">17</div>

</div>

<div class="section">

<div class="kicker">Chapter Seven, continued</div>
<p>After the 2-up/2-back shuffle — which moves about {den_move} of all players — the spread <i>widens</i> to {den_s2}.</p>
<p>Read that again: the movement rule designed to sort players actually leaves courts <b>less balanced</b> than they started. Most of that movement is mechanical, not earned.</p>
<div class="pgnum">18</div>

</div>

<div class="section">

<div class="kicker">Case Study — May 4, 2026</div>
<svg style="display:block;" viewbox="0 0 420 500" width="100%">
<text fill="var(--navy)" font-family="'Trebuchet MS',sans-serif" font-size="12" font-weight="bold" text-anchor="middle" x="135" y="14">True rank after S1</text>
<text fill="var(--navy)" font-family="'Trebuchet MS',sans-serif" font-size="12" font-weight="bold" text-anchor="middle" x="340" y="14">Shootout 2 courts</text>
<rect fill="var(--tan)" height="140" rx="6" stroke="var(--navy-2)" stroke-width="0.75" width="140" x="270" y="26"></rect>
<text fill="var(--navy)" font-family="'Trebuchet MS',sans-serif" font-size="11" font-weight="bold" x="280" y="42">Court 1</text>
<rect fill="var(--tan)" height="140" rx="6" stroke="var(--navy-2)" stroke-width="0.75" width="140" x="270" y="181"></rect>
<text fill="var(--navy)" font-family="'Trebuchet MS',sans-serif" font-size="11" font-weight="bold" x="280" y="197">Court 2</text>
<rect fill="var(--tan)" height="140" rx="6" stroke="var(--navy-2)" stroke-width="0.75" width="140" x="270" y="336"></rect>
<text fill="var(--navy)" font-family="'Trebuchet MS',sans-serif" font-size="11" font-weight="bold" x="280" y="352">Court 3</text>
<line stroke="#1E8449" stroke-width="1.5" x1="135" x2="290" y1="30" y2="56"></line>
<line stroke="#1E8449" stroke-width="1.5" x1="135" x2="290" y1="70" y2="88"></line>
<line stroke="#E8871E" stroke-width="2" x1="135" x2="290" y1="110" y2="307"></line>
<line stroke="#E8871E" stroke-width="2" x1="135" x2="290" y1="150" y2="243"></line>
<line stroke="#E8871E" stroke-width="2" x1="135" x2="290" y1="190" y2="366"></line>
<line stroke="#E8871E" stroke-width="2" x1="135" x2="290" y1="230" y2="152"></line>
<line stroke="#E8871E" stroke-width="2" x1="135" x2="290" y1="270" y2="120"></line>
<line stroke="#E8871E" stroke-width="2" x1="135" x2="290" y1="310" y2="430"></line>
<line stroke="#E8871E" stroke-width="2" x1="135" x2="290" y1="350" y2="211"></line>
<line stroke="#1E8449" stroke-width="1.5" x1="135" x2="290" y1="390" y2="462"></line>
<line stroke="#E8871E" stroke-width="2" x1="135" x2="290" y1="430" y2="275"></line>
<line stroke="#1E8449" stroke-width="1.5" x1="135" x2="290" y1="470" y2="398"></line>
<text dominant-baseline="central" fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="11" text-anchor="end" x="125" y="30">E. Kramer</text>
<text dominant-baseline="central" fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="11" text-anchor="end" x="125" y="70">P. Barnett</text>
<text dominant-baseline="central" fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="11" text-anchor="end" x="125" y="110">P. Rillero</text>
<text dominant-baseline="central" fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="11" text-anchor="end" x="125" y="150">S. Ludick</text>
<text dominant-baseline="central" fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="11" text-anchor="end" x="125" y="190">J. Barroso</text>
<text dominant-baseline="central" fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="11" text-anchor="end" x="125" y="230">L. Zolnierczyk</text>
<text dominant-baseline="central" fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="11" text-anchor="end" x="125" y="270">D. Christensen</text>
<text dominant-baseline="central" fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="11" text-anchor="end" x="125" y="310">C. McCormick</text>
<text dominant-baseline="central" fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="11" text-anchor="end" x="125" y="350">K. Backstrom</text>
<text dominant-baseline="central" fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="11" text-anchor="end" x="125" y="390">A. Tinstman</text>
<text dominant-baseline="central" fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="11" text-anchor="end" x="125" y="430">N. Whitson</text>
<text dominant-baseline="central" fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="11" text-anchor="end" x="125" y="470">P. Batie</text>
<circle cx="135" cy="30" fill="var(--navy)" r="2.5"></circle>
<circle cx="135" cy="70" fill="var(--navy)" r="2.5"></circle>
<circle cx="135" cy="110" fill="var(--navy)" r="2.5"></circle>
<circle cx="135" cy="150" fill="var(--navy)" r="2.5"></circle>
<circle cx="135" cy="190" fill="var(--navy)" r="2.5"></circle>
<circle cx="135" cy="230" fill="var(--navy)" r="2.5"></circle>
<circle cx="135" cy="270" fill="var(--navy)" r="2.5"></circle>
<circle cx="135" cy="310" fill="var(--navy)" r="2.5"></circle>
<circle cx="135" cy="350" fill="var(--navy)" r="2.5"></circle>
<circle cx="135" cy="390" fill="var(--navy)" r="2.5"></circle>
<circle cx="135" cy="430" fill="var(--navy)" r="2.5"></circle>
<circle cx="135" cy="470" fill="var(--navy)" r="2.5"></circle>
<circle cx="290" cy="56" fill="var(--navy)" r="2.5"></circle>
<circle cx="290" cy="88" fill="var(--navy)" r="2.5"></circle>
<circle cx="290" cy="307" fill="var(--navy)" r="2.5"></circle>
<circle cx="290" cy="243" fill="var(--navy)" r="2.5"></circle>
<circle cx="290" cy="366" fill="var(--navy)" r="2.5"></circle>
<circle cx="290" cy="152" fill="var(--navy)" r="2.5"></circle>
<circle cx="290" cy="120" fill="var(--navy)" r="2.5"></circle>
<circle cx="290" cy="430" fill="var(--navy)" r="2.5"></circle>
<circle cx="290" cy="211" fill="var(--navy)" r="2.5"></circle>
<circle cx="290" cy="462" fill="var(--navy)" r="2.5"></circle>
<circle cx="290" cy="275" fill="var(--navy)" r="2.5"></circle>
<circle cx="290" cy="398" fill="var(--navy)" r="2.5"></circle>
<text fill="var(--ink)" font-family="'Trebuchet MS',sans-serif" font-size="10.5" text-anchor="middle" x="210" y="488">Green: matched · Amber: 1 tier off</text>
</svg>
<div class="pgnum">19</div>

</div>

<div class="section">

<div class="kicker">Chapter Seven, Continued</div>
<h2>Perfect, Then Scrambled</h2>
<p>On May 4, 2026, the DEN got the Shootout 1 court assignments exactly right. Every one of twelve players landed on the court matching their true skill rank — zero mismatches. Step and Percentage worked as designed.</p>
<p>Then 2-up/2-back moved players for Shootout 2, using only that morning's three games as its signal. The result: eight of twelve players — two-thirds of the field — landed in the wrong pool.</p>
<p>Court 1 shows the damage directly. Eric Kramer and Peter Barnett, the two highest-rated players in the field, ended up paired together by the shuffle and beat Dwight Christensen and Lidia Zolnierczyk — correctly separated into a lower tier just one session earlier — <b>11–4</b>. The movement rule undid a correct assignment using less information than the assignment it replaced.</p>
<div class="pgnum">20</div>

</div>

<div class="section">

<div class="kicker">Chapter Seven, continued</div>
<p style="opacity:0.6;font-style:italic;">Reserved for future content.</p>
<div class="pgnum">21</div>

</div>

<div class="section">

<div class="kicker">Chapter Eight</div>
<h2>What We Tested — and How We Scored It</h2>
<p>There is no shortage of ideas for assigning courts. To compare them fairly, we replayed the last 90 days of actual shootouts — same players, same signups, same court counts — under each candidate method.</p>
<p>Every method gets two scores. <b>Court tightness:</b> how close in skill the four players on each court are — a smaller spread means fairer games. <b>Shuffle:</b> what share of players change courts between the two sessions — some movement is healthy; constant mechanical reshuffling is not.</p>
<p>Today’s system is the baseline to beat: a combined spread of {den_comb}, with {den_move} of players moving mid-morning.</p>
<div class="pgnum">22</div>

</div>

<div class="section">

<div class="kicker">Within-Court Skill Spread — Current System</div>
<div class="stat-stack" style="height:72%;">
<div class="stat"><div class="num">{den_s1}</div><div class="lbl">Shootout 1 average spread (DEN step / percentage)</div></div>
<div class="stat" style="border-left-color:#b3543a;"><div class="num">{den_s2}</div><div class="lbl">Shootout 2 average spread (after 2-up/2-back)</div></div>
<div class="stat"><div class="num">{den_comb}</div><div class="lbl">combined baseline — the number to beat</div></div>
</div>
<div class="pgnum">23</div>

</div>

<div class="section">

<div class="kicker">Four Families of Ideas</div>
<div class="factor"><b>1 · FIX THE STARTING LINEUP</b><span>Build Shootout 1 courts from player ratings instead of step and percentage. The morning starts fair; everything else stays exactly as it is.</span></div>
<div class="factor"><b>2 · SOFTEN THE SHUFFLE</b><span>Keep movement between sessions, but move one player up and one down per court instead of two. Less churn, same reward for winning.</span></div>
<div class="factor"><b>3 · LET RESULTS DRIVE SHOOTOUT 2</b><span>Re-rank everyone using their Shootout 1 results — weighted by who they faced — and rebuild the courts. A dial controls how strongly one morning moves you: steady, balanced, or fast.</span></div>
<div class="factor"><b>4 · TARGETED SWAPS ONLY</b><span>Leave courts alone except in special cases: two players nearly tied at a court boundary, or someone dramatically out-playing or under-playing their rating.</span></div>
<div class="pgnum">24</div>

</div>

<div class="section">

<div class="kicker">Chapter Eight, continued</div>
<h2>How to Read the Scorecard</h2>
<p><b>Better-matched courts</b> is the improvement in court tightness versus today. +37% means the skill spread inside a typical court shrinks by more than a third.</p>
<p><b>Players changing courts</b> is the share of players sitting on a different court in Shootout 2 than Shootout 1. Today’s 2-up/2-back moves about {den_move} — the most of anything we tested.</p>
<p><b>Effort:</b> “Already automated” rows run through the rating engine this project already builds and runs, unattended, after every play date — nothing new to build. “New automation” rows would need new tooling, triggered live on-site in the tight window between Shootout 1 and Shootout 2.</p>
<p>The two ★ rows are the recommendation — a starting step and a destination.</p>
<div class="pgnum">25</div>

</div>

<div class="section">

<div class="kicker">The Scorecard</div>
<table class="btable">
<tr><th style="text-align:left;">Approach</th><th>Better-Matched Courts</th><th>Players Changing Courts</th><th>Effort</th></tr>
          {option_rows}
        </table>
<p style="font-size:clamp(8.5px,1vw,12px);color:#8a7f6a;margin-top:3%;">Scored across the last 90 days of real sessions. Today’s system: {den_comb} combined spread, {den_move} of players moving.</p>
<div class="pgnum">26</div>

</div>

<div class="section">

<div class="kicker">Chapter Nine</div>
<h2>The Recommendation: Two Phases</h2>
<div class="phase">
<b>PHASE 1 — Rating-seeded start, gentler shuffle</b>
<span>Seed Shootout 1 by rating instead of step and percentage; soften the mid-morning shuffle to one-up/one-back. Runs unattended overnight — Elo-based seedings load automatically after midnight, before anyone’s on the courts. Already built, tested, and validated end to end.</span>
<div class="metric">{ph1_vs} better-matched courts · combined spread {ph1_comb}</div>
</div>
<div class="phase">
<b>PHASE 2 — Results-driven Shootout 2, balanced dial</b>
<span>Shootout 2 courts rebuilt from Shootout 1 results, weighted by opponent strength — movement is earned, not mechanical. Unlike Phase 1, this can’t run unattended: it has to be triggered in the narrow window right after Shootout 1 wraps, from the courts, by someone with access. (For the technically curious: appendix A.)</span>
<div class="metric">{ph2_vs} better-matched courts · combined spread {ph2_comb}</div>
</div>
<div class="pgnum">27</div>

</div>

<div class="section">

<div class="kicker">Chapter Nine, Continued</div>
<h2>This Isn’t a Settings Toggle</h2>
<p>Everything on the previous page is possible because of work already done, not work still theoretical. DEN has no setting for rating-based seeding or results-driven reshuffling — both phases require quietly overriding DEN’s own numbers from the outside.</p>
<p>The technique: write a synthetic value into DEN’s own Ladder Step field for each player, then let DEN’s own “Seed Players” button do the actual grouping. DEN never needs to know a rating model is behind the number it’s reading.</p>
<p>Phase 1 (rating-seeded Shootout 1) is proven — tested live against a real signup sheet, full removal-to-Start-Event flow, working end to end. Phase 2 extends the same technique to Shootout 2: after Shootout 1’s games post, replay them through the rating engine, then write fresh synthetic Step values reflecting that recalculation before Shootout 2 seeds.</p>
<p>The two phases differ in more than scope, though. Phase 1 finishes before anyone checks in — the seeding is already loaded and waiting when the first player arrives. Phase 2 can’t work that way: it has to fire live, on the spot, in the gap between Shootout 1’s last game and Shootout 2’s first. That makes its remaining hurdle a question of who’s there to trigger it, not whether the code works.</p>
<div class="pgnum">28</div>

</div>

<div class="section">

<div class="kicker">What Changes for a Player</div>
<div class="factor"><b>YOUR FIRST COURT FITS</b><span>Shootout 1 placement reflects how you’ve actually been playing — not where you stood one bad morning three weeks ago.</span></div>
<div class="factor"><b>MOVEMENT MEANS SOMETHING</b><span>Moving up is earned by beating expectations, weighted by who you faced — not by finishing top-two on an easy court.</span></div>
<div class="factor"><b>EVERY GAME COUNTS</b><span>Your rating updates after every game, with recent play weighted most.</span></div>
<div class="factor"><b>NOTHING ELSE CHANGES</b><span>Same courts, same times, same shootout format. Only the seeding logic improves.</span></div>
<div class="pgnum">29</div>

</div>

<div class="section">

<div class="kicker" style="color:#8a7f6a;">Technical Appendix · A</div>
<h2>The Model Mechanics</h2>
<p style="font-size:clamp(9.5px,1.12vw,13.5px);">For readers who want the nitty gritty. Every rating update follows one formula:</p>
<div class="mono">ΔR = K × (S − E) × M<br/><br/>
S  = result (1 win, 0 loss)<br/>
E  = expected win prob = 1 / (1 + 10^((R<sub>opp</sub> − R<sub>team</sub>)/400))<br/>
M = margin multiplier = ln(margin + 1)</div>
<p style="font-size:clamp(9px,1.08vw,13px);">Team ratings are the average of the two partners; all four players update after every rated game.</p>
<div class="pgnum">30</div>

</div>

<div class="section">

<div class="kicker" style="color:#8a7f6a;">Technical Appendix · A, continued</div>
<div class="factor"><b>FULL CUMULATIVE HISTORY</b><span>Your rating reflects your entire rated career — no window, no reset. Long tenure carries no unearned inflation; your full track record simply counts, for better or worse.</span></div>
<div class="factor"><b>PROVISIONAL K</b><span>K starts at 40 for a player’s first game and declines linearly to 20 by game 60, then holds. New players converge quickly; established ratings stay stable.</span></div>
<div class="factor"><b>FRESHNESS WINDOW</b><span>Eligibility and freshness are judged separately from your rating, using only your own last 60 real games — never blended with anyone else’s. This determines your Freshness Tier, not your rating itself.</span></div>
<div class="factor"><b>STEP ARITHMETIC</b><span>Step for your next playdate is your current court number, minus one for a top-two finish (floored at 1 — the best court has nowhere higher to go), plus one for a bottom-two finish (uncapped). A 3-court, 12-player day produces exactly four players at Step 1, four at Step 2, two at Step 3, and two at Step 4 — the bottom performers on the worst court carry a Step higher than any court that day actually had, into whatever court count shows up next time.</span></div>
<div class="factor"><b>STEP ARITHMETIC</b><span>Step for your next playdate is your current court number, minus one for a top-two finish (floored at 1 — the best court has nowhere higher to go), plus one for a bottom-two finish (uncapped). A 3-court, 12-player day produces exactly four players at Step 1, four at Step 2, two at Step 3, and two at Step 4 — the bottom performers on the worst court carry a Step higher than any court that day actually had, into whatever court count shows up next time.</span></div>
<div class="pgnum">31</div>

</div>

<div class="section">

<div class="kicker" style="color:#8a7f6a;">Technical Appendix · B</div>
<h2>Data Hygiene &amp; Display</h2>
<div class="factor"><b>WHAT COUNTS</b><span>Every posted shootout game since Jan {first_year}. Placeholder entries (tryouts, drop-ins), guest players, and flagged data errors are excluded from ratings; known name glitches are corrected at load.</span></div>
<div class="factor"><b>SHARED-NAME PLACEHOLDER</b><span>“New Player Tryout” games are excluded from ratings entirely, not just flagged. Different people play under that same placeholder name from week to week, so there is no way to attribute those results to any one consistent player’s skill.</span></div>
<div class="factor"><b>LEADERBOARD QUALIFICATION</b><span>At least 24 rated games within the past 180 days. Everyone else still carries a rating — shown with reduced confidence, pulled toward 1,000 in proportion to sample size.</span></div>
<div class="factor"><b>FRESHNESS</b><span>No continuous penalty — freshness is a hard cutoff, not a haircut. Very Fresh (0–90 days) and Mature (91–180 days) players appear on the main leaderboard; Stale and Very Stale players are shown separately, ratings unaffected.</span></div>
<div class="pgnum">32</div>

</div>

<div class="section">

<div class="kicker" style="color:#8a7f6a;">Technical Appendix · B, continued</div>
<div class="factor"><b>EXPECTATION COMPRESSION</b><span>Affects what is shown, not what is earned: displayed win probabilities compress the rating gap by 0.92 before the logistic, matching observed SAM outcomes ({pct_0_100} / {pct_101_200} / {pct_201_300}%). The actual rating calculation does not use this compressed figure at all.</span></div>
<div class="factor"><b>VALIDATION</b><span>Predictions are checked against outcomes across the full pool every run. Gaps between individual actual and expected win rates reflect normal variance and close as games accumulate; aggregate calibration is what the model is tuned for.</span></div>
<div class="factor"><b>SCENARIO REPLAY</b><span>Assignment alternatives were tested against the last 90 days of real sessions — same signups, same court counts — not simulations of hypothetical players.</span></div>
<div class="mono" style="margin-top:3%;">Every number in this book was computed from the underlying rating engine as of the snapshot date on the cover. It is not a live document -- re-run the report to produce a new dated snapshot after major changes.</div>
<p style="font-style:italic;opacity:0.75;">— end —</p>
<div class="pgnum">33</div>

</div>

<div class="section back-cover-section">

<div class="rule" style="width:56px;height:2px;background:var(--accent);"></div>
<h1 style="font-size:clamp(16px,2.2vw,26px);font-weight:normal;">See Where You Stand</h1>
<p style="font-size:clamp(10px,1.25vw,14px);line-height:1.6;">
        Every rating, every game in this book<br/>is available live, updated after each play date:</p>
<p style="font-size:clamp(10px,1.3vw,14.5px);"><a href="https://billpollock1-hue.github.io/sam-pickleball/">Anthem SAM · Live Results</a></p>
<p style="font-size:11px;opacity:0.6;margin-top:4%;">Data through {latest} · {n_games:,} games</p>

</div>
</div>
</body>
</html>"""

OUT_PATH.write_text(html, encoding="utf-8")
print(f"Saved: {OUT_PATH}")
