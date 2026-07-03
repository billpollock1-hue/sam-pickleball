#!/usr/bin/env python3
"""
Storybook presentation of the court-assignment case — an open-faced book
with 3D page turns. Self-contained HTML; exhibits pull live numbers from
the master history so the book never goes stale.

Proof of concept: cover + two spreads + closing teaser.
"""

from pathlib import Path

import pandas as pd

ENGINE_DIR = Path(__file__).resolve().parent
REPO_ROOT = ENGINE_DIR.parent
DATA_PATH = REPO_ROOT / "data" / "master_history_raw.csv"
OUT_PATH = REPO_ROOT / "output" / "storybook.html"

# ── Live numbers for exhibits ─────────────────────────────────────────────────
raw = pd.read_csv(DATA_PATH)
posted = pd.to_datetime(raw["posted"], errors="coerce").dropna()
n_games = len(raw)
n_dates = posted.dt.date.nunique()
first_year = posted.min().year
latest = posted.max().strftime("%B %Y")

players = set()
for col in ("winning_team", "losing_team"):
    for team in raw[col].dropna():
        for p in str(team).split(" / "):
            players.add(p.strip())
n_players = len(players)

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>The Case for Better Courts</title>
<style>
  :root {{
    --navy:   #1F4E79;
    --navy-2: #2E75B6;
    --paper:  #FBF7EE;
    --paper-edge: #EFE8D8;
    --ink:    #33302A;
    --accent: #C9A84C;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{ height: 100%; }}
  body {{
    font-family: Georgia, 'Times New Roman', serif;
    background: radial-gradient(ellipse at center, #3d5a75 0%, #24384d 70%);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    padding: 24px 12px;
    overflow-x: hidden;
  }}

  .book-wrap {{ perspective: 2400px; }}

  .book {{
    position: relative;
    width: min(92vw, 980px);
    aspect-ratio: 2 / 1.35;
    transform-style: preserve-3d;
  }}

  /* Static left base (shows the current left page beneath flipping sheets) */
  .page {{
    position: absolute;
    top: 0;
    width: 50%;
    height: 100%;
    background: var(--paper);
    padding: 5.2% 5%;
    overflow: hidden;
  }}
  .page.left  {{
    left: 0;
    border-radius: 12px 0 0 12px;
    box-shadow: inset -14px 0 24px -14px rgba(0,0,0,0.35);
  }}
  .page.right {{
    right: 0;
    border-radius: 0 12px 12px 0;
    box-shadow: inset 14px 0 24px -14px rgba(0,0,0,0.30);
  }}

  /* Flipping sheets live on the right half, hinged at the spine */
  .sheet {{
    position: absolute;
    top: 0;
    left: 50%;
    width: 50%;
    height: 100%;
    transform-origin: left center;
    transform-style: preserve-3d;
    transition: transform 0.9s cubic-bezier(0.4, 0.05, 0.3, 1);
    cursor: pointer;
  }}
  .sheet.flipped {{ transform: rotateY(-180deg); }}

  .face {{
    position: absolute;
    inset: 0;
    backface-visibility: hidden;
    -webkit-backface-visibility: hidden;
    background: var(--paper);
    padding: 5.2% 5%;
    overflow: hidden;
  }}
  .face.front {{
    border-radius: 0 12px 12px 0;
    box-shadow: inset 14px 0 24px -14px rgba(0,0,0,0.30);
  }}
  .face.back {{
    transform: rotateY(180deg);
    border-radius: 12px 0 0 12px;
    box-shadow: inset -14px 0 24px -14px rgba(0,0,0,0.35);
  }}

  /* ── Cover ── */
  .cover {{
    background: linear-gradient(145deg, var(--navy) 0%, #16385a 100%);
    color: #fff;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    gap: 18px;
  }}
  .cover .rule {{ width: 56px; height: 2px; background: var(--accent); }}
  .cover h1 {{ font-size: clamp(20px, 3.2vw, 34px); font-weight: normal; letter-spacing: 1px; line-height: 1.25; }}
  .cover .sub {{ font-size: clamp(11px, 1.4vw, 15px); opacity: 0.85; font-style: italic; }}
  .cover .hint {{ position: absolute; bottom: 7%; font-size: 12px; opacity: 0.55; letter-spacing: 0.5px; }}

  /* ── Page typography ── */
  .kicker {{
    font-family: 'Trebuchet MS', Verdana, sans-serif;
    font-size: clamp(9px, 1.05vw, 12px);
    letter-spacing: 2.2px;
    text-transform: uppercase;
    color: var(--navy-2);
    margin-bottom: 4%;
  }}
  h2 {{ font-size: clamp(16px, 2.1vw, 24px); color: var(--navy); font-weight: normal; margin-bottom: 4%; line-height: 1.25; }}
  p  {{ font-size: clamp(11px, 1.35vw, 15.5px); line-height: 1.62; color: var(--ink); margin-bottom: 3.5%; }}
  .pgnum {{
    position: absolute; bottom: 4.5%;
    font-size: 11px; color: #9a8f7a;
    font-family: Georgia, serif;
  }}
  .page.left .pgnum, .face.back .pgnum {{ left: 7%; }}
  .page.right .pgnum, .face.front .pgnum {{ right: 7%; }}

  /* ── Exhibit styling ── */
  .stat-stack {{ display: flex; flex-direction: column; gap: 5%; height: 82%; justify-content: center; }}
  .stat {{
    border-left: 4px solid var(--navy-2);
    background: #f3ecdd;
    padding: 4.5% 6%;
    border-radius: 0 8px 8px 0;
  }}
  .stat .num {{ font-size: clamp(20px, 3vw, 34px); color: var(--navy); }}
  .stat .lbl {{ font-family: 'Trebuchet MS', sans-serif; font-size: clamp(9px, 1.1vw, 12.5px); color: #6d6353; letter-spacing: 0.4px; margin-top: 2px; }}

  .factor {{
    background: #f3ecdd;
    border-radius: 8px;
    padding: 4% 5.5%;
    margin-bottom: 4%;
  }}
  .factor b {{ display: block; font-family: 'Trebuchet MS', sans-serif; font-size: clamp(10px, 1.2vw, 13.5px); color: var(--navy); margin-bottom: 1.5%; }}
  .factor span {{ font-size: clamp(10.5px, 1.25vw, 14px); line-height: 1.5; color: var(--ink); }}
  .prob-line {{
    margin-top: 5%;
    padding: 4% 5.5%;
    background: var(--navy);
    color: #fff;
    border-radius: 8px;
    font-size: clamp(10.5px, 1.25vw, 14px);
    line-height: 1.55;
  }}
  .prob-line b {{ color: var(--accent); }}

  .tbc {{
    height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    gap: 4%;
    color: #8a7f6a;
    font-style: italic;
  }}

  /* ── Controls ── */
  .controls {{
    margin-top: 20px;
    display: flex;
    align-items: center;
    gap: 18px;
    color: #cfdae6;
    font-family: 'Trebuchet MS', sans-serif;
    font-size: 13px;
  }}
  .controls button {{
    background: rgba(255,255,255,0.12);
    border: 1px solid rgba(255,255,255,0.3);
    color: #fff;
    border-radius: 20px;
    padding: 7px 18px;
    cursor: pointer;
    font-size: 13px;
  }}
  .controls button:hover {{ background: rgba(255,255,255,0.25); }}
  .controls button:disabled {{ opacity: 0.3; cursor: default; }}

  /* ── Phone: single page ── */
  @media (max-width: 640px) {{
    .book {{ width: 94vw; aspect-ratio: 1 / 1.45; }}
    .page.left {{ display: none; }}
    .page.right, .face.front, .face.back {{ width: 100%; left: 0; right: auto; border-radius: 10px; }}
    .sheet {{ left: 0; width: 100%; transform-origin: center left; }}
    .face.back .pgnum {{ left: auto; right: 7%; }}
  }}
</style>
</head>
<body>

<div class="book-wrap">
  <div class="book" id="book">

    <!-- static left base: revealed under the last flipped sheet -->
    <div class="page left" id="baseLeft"></div>
    <!-- static right base: what shows when all sheets are flipped -->
    <div class="page right">
      <div class="tbc">
        <div style="font-size:34px;">&#10087;</div>
        <p style="font-style:italic;">The full story — the evidence, the root cause,<br>
        what we tested, and the recommendation —<br>continues from here.</p>
        <p style="font-size:12px;">Proof of concept &middot; {latest}</p>
      </div>
      <div class="pgnum">5</div>
    </div>

    <!-- Sheet 1: cover | challenge narrative -->
    <div class="sheet" id="s0" style="z-index:3;">
      <div class="face front cover">
        <div class="rule"></div>
        <h1>The Case for<br>Better Courts</h1>
        <div class="rule"></div>
        <div class="sub">Using four years of shootout data to make<br>every SAM session more competitive</div>
        <div class="hint">click to open &#8250;</div>
      </div>
      <div class="face back">
        <div class="kicker">Chapter One</div>
        <h2>The Challenge: Moving from Perception to Evidence</h2>
        <p>Players in the SAM shootout have raised concerns about court competitiveness &mdash; too many lopsided games, courts that feel mismatched.</p>
        <p>Perception is a starting point, but it is not enough to diagnose the problem or evaluate solutions. We need an objective metric: a way to measure the skill gap between teams in any given game, consistently, across thousands of games and multiple years.</p>
        <p>Fortunately, we have exactly the raw material that requires.</p>
        <div class="pgnum">1</div>
      </div>
    </div>

    <!-- Sheet 2: challenge exhibit | metric narrative -->
    <div class="sheet" id="s1" style="z-index:2;">
      <div class="face front">
        <div class="kicker">The Raw Material</div>
        <div class="stat-stack">
          <div class="stat"><div class="num">{n_games:,}</div><div class="lbl">games recorded since {first_year}</div></div>
          <div class="stat"><div class="num">{n_dates:,}</div><div class="lbl">play dates captured</div></div>
          <div class="stat"><div class="num">{n_players}</div><div class="lbl">players who have taken the court</div></div>
        </div>
        <div class="pgnum">2</div>
      </div>
      <div class="face back">
        <div class="kicker">Chapter Two</div>
        <h2>The Metric: Modified Elo</h2>
        <p>Elo is a rating system originally developed for chess and widely used in competitive sports. Every player starts at 1,000. After each game, all four players&rsquo; ratings update based on the result versus what the model predicted.</p>
        <p>Your team&rsquo;s rating is the average of you and your partner. The bigger the rating gap between two teams, the more confidently the model expects the stronger side to win &mdash; and four years of SAM results let us check those expectations against reality.</p>
        <div class="pgnum">3</div>
      </div>
    </div>

    <!-- Sheet 3: metric exhibit | (back page under construction) -->
    <div class="sheet" id="s2" style="z-index:1;">
      <div class="face front">
        <div class="kicker">Three Factors Drive Every Update</div>
        <div class="factor"><b>1 &middot; RESULT</b><span>Winning earns points; losing costs points.</span></div>
        <div class="factor"><b>2 &middot; MARGIN</b><span>An 11&ndash;2 win moves ratings more than an 11&ndash;9 win.</span></div>
        <div class="factor"><b>3 &middot; OPPONENT STRENGTH</b><span>Beating a strong team earns more than beating a weak one.</span></div>
        <div class="prob-line">In observed SAM games, the higher-rated team wins <b>57%</b> of the time at a 100-point gap, <b>66%</b> at 200 points, and <b>78%</b> at 300 points.</div>
        <div class="pgnum">4</div>
      </div>
      <div class="face back">
        <div class="tbc">
          <p>&mdash; more spreads to come &mdash;</p>
        </div>
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
  const sheets = [document.getElementById('s0'), document.getElementById('s1'), document.getElementById('s2')];
  const N = sheets.length;
  let flipped = 0;   // number of sheets turned

  const spreadNames = ["Cover", "The Challenge", "The Metric", "To be continued"];

  function render() {{
    sheets.forEach((s, i) => {{
      s.classList.toggle('flipped', i < flipped);
      // flipped sheets stack left in the order turned; unflipped stack right
      s.style.zIndex = (i < flipped) ? (i + 1) : (N - i + 10);
    }});
    document.getElementById('btnBack').disabled = (flipped === 0);
    document.getElementById('btnFwd').disabled  = (flipped === N);
    document.getElementById('pageInfo').textContent = spreadNames[flipped];
  }}

  function turn(dir) {{
    flipped = Math.min(N, Math.max(0, flipped + dir));
    render();
  }}

  // Click: right half forward, left half back
  document.getElementById('book').addEventListener('click', (e) => {{
    const rect = e.currentTarget.getBoundingClientRect();
    turn(e.clientX - rect.left > rect.width / 2 ? 1 : -1);
  }});

  // Keyboard
  document.addEventListener('keydown', (e) => {{
    if (e.key === 'ArrowRight' || e.key === ' ') turn(1);
    if (e.key === 'ArrowLeft') turn(-1);
  }});

  // Swipe
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
print(f"Live numbers: {n_games:,} games, {n_dates:,} play dates, {n_players} players, through {latest}")
