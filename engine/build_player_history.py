#!/usr/bin/env python3
"""
Builds a self-contained HTML player history viewer with player dropdown.
All data is embedded as JSON -- no server required.
Ratings sourced from Player_Game_Log in pickleball_model_latest.xlsx,
same source as build_session_viewer.py, for consistency.
"""

import sys, json
from pathlib import Path
from collections import defaultdict
import pandas as pd

ENGINE_DIR = Path(__file__).resolve().parent
REPO_ROOT  = ENGINE_DIR.parent

MODEL_PATH = REPO_ROOT / "output" / "pickleball_model_latest.xlsx"
OUT_PATH   = REPO_ROOT / "output" / "player_history.html"

# ── Load Player_Game_Log ──────────────────────────────────────────────────────
pgl = pd.read_excel(MODEL_PATH, sheet_name="Player_Game_Log")
pgl["posted_dt"] = pd.to_datetime(pgl["posted_dt"])
pgl["date_str"]  = pgl["posted_dt"].dt.strftime("%Y-%m-%d")
pgl["time_str"]  = pgl["posted_dt"].dt.strftime("%H:%M")
pgl["year_str"]  = pgl["posted_dt"].dt.strftime("%Y")

# ── Build player_games dict (grouped by player, not by date) ─────────────────
player_games = defaultdict(list)

for _, r in pgl.sort_values("posted_dt").iterrows():
    is_win  = bool(r["is_win"])
    pf      = int(r["pf"]) if pd.notna(r.get("pf")) else 0
    pa      = int(r["pa"]) if pd.notna(r.get("pa")) else 0
    adjusted = str(r.get("include_in_ratings", "No")).strip() == "Yes"

    if adjusted:
        pre    = round(float(r["player_pre_rating"]))
        post   = round(float(r["player_post_rating"]))
        change = round(float(r["player_post_rating"]) - float(r["player_pre_rating"]), 1)
    else:
        pre = post = change = None
    team    = round(float(r["team_pre_rating"]))
    opp     = round(float(r["opp_team_pre_rating"]))
    gap     = round(team - opp)
    opp2    = r.get("opp2", "")
    opp2    = "" if pd.isna(opp2) else str(opp2)
    partner = r.get("partner", "")
    partner = "" if pd.isna(partner) else str(partner)

    score = f"{pf}\u2013{pa}"

    player_games[str(r["player"])].append({
        "date":       r["date_str"],
        "year":       r["year_str"],
        "time":       r["time_str"],
        "pool":       str(r.get("pool", "") or ""),
        "shootout":   int(r.get("shootout", 1) or 1),
        "partner":    partner,
        "opp1":       str(r.get("opp1", "") or ""),
        "opp2":       opp2,
        "win":        is_win,
        "score":      score,
        "teamRating": int(team),
        "oppRating":  int(opp),
        "gap":        int(gap),
        "pre":        pre,
        "change":     change,
        "post":       post,
        "adjusted":   adjusted,
        "cumPre":     round(float(r["player_pre_rating"])),
    })

players_sorted = sorted(player_games.keys())
data_json      = json.dumps(player_games)
players_json   = json.dumps(players_sorted)

print(f"Players included: {len(players_sorted)}")

# ── Build HTML ────────────────────────────────────────────────────────────────
html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SAM Shootout — Player History</title>
<style>
  :root {{
    --blue-dark: #1F4E79;
    --blue-mid:  #2E75B6;
    --blue-light:#D6E4F0;
    --green:     #E2EFDA;
    --red:       #FCE4D6;
    --gray:      #F5F5F5;
    --border:    #CCCCCC;
    --text:      #333333;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: Calibri, Arial, sans-serif; font-size: 14px; color: var(--text); background: #fff; }}

  .back-badge {{ position: fixed; top: 10px; left: 10px; z-index: 1000;
                 background: #1F4E79; color: #fff; font-size: 12px;
                 padding: 6px 12px; border-radius: 6px; text-decoration: none;
                 box-shadow: 0 1px 4px rgba(0,0,0,0.2); }}
  .back-badge:hover {{ background: #163a5c; }}

  header {{
    background: var(--blue-dark);
    color: #fff;
    padding: 18px 28px;
    display: flex;
    align-items: center;
    gap: 20px;
    flex-wrap: wrap;
  }}
  header h1 {{ font-size: 20px; font-weight: bold; letter-spacing: 0.3px; }}
  header .subtitle {{ font-size: 13px; opacity: 0.8; }}

  .controls {{
    padding: 16px 28px;
    background: var(--gray);
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }}
  .controls label {{ font-weight: bold; color: var(--blue-dark); }}
  .controls select {{
    padding: 6px 12px;
    border: 1px solid var(--border);
    border-radius: 4px;
    font-size: 14px;
    background: #fff;
    cursor: pointer;
  }}
  .refresh-btn {{ background: #1F4E79; color: #fff; font-size: 12px;
                  padding: 6px 12px; border: none; border-radius: 4px;
                  cursor: pointer; white-space: nowrap; }}
  .refresh-btn:hover {{ background: #163a5c; }}
  #freshness-hint {{ padding: 6px 28px; font-size: 11px; color: #888;
                     background: #fafafa; border-bottom: 1px solid var(--border); }}
  .sec-head {{ display: flex; align-items: center; gap: 10px; }}
  .sec-head h2 {{ flex: 1; }}
  .sec-head label {{ font-weight: bold; color: var(--blue-dark); font-size: 13px; }}
  .sec-head select {{
    padding: 5px 10px;
    border: 1px solid var(--border);
    border-radius: 4px;
    font-size: 13px;
    background: #fff;
    cursor: pointer;
    margin-bottom: 8px;
  }}
  .controls .stat-pills {{ margin-left: auto; display: flex; gap: 10px; flex-wrap: wrap; }}
  .pill {{
    background: var(--blue-light);
    color: var(--blue-dark);
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 13px;
    font-weight: bold;
  }}

  main {{ padding: 20px 28px; display: flex; flex-direction: column; gap: 28px; }}

  section h2 {{
    font-size: 15px;
    font-weight: bold;
    color: var(--blue-dark);
    border-bottom: 2px solid var(--blue-dark);
    padding-bottom: 6px;
    margin-bottom: 12px;
  }}

  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }}
  th {{
    background: var(--blue-mid);
    color: #fff;
    padding: 7px 10px;
    text-align: center;
    font-weight: bold;
    white-space: nowrap;
  }}
  th.left {{ text-align: left; }}
  td {{
    padding: 6px 10px;
    border-bottom: 1px solid var(--border);
    text-align: center;
    white-space: nowrap;
  }}
  td.left {{ text-align: left; }}
  tr:nth-child(even) td {{ background: var(--blue-light); }}
  tr:hover td {{ background: #c5d9ef; }}

  .pos {{ background: var(--green) !important; font-weight: bold; color: #276221; }}
  .neg {{ background: var(--red)   !important; font-weight: bold; color: #9C3B1B; }}
  .zero {{ color: #888; }}
  .unadj-note {{ color: #b8860b; font-weight: bold; cursor: help; }}
  .unadj-cell {{ color: #999; font-style: italic; }}
  .win-badge  {{ color: #276221; font-weight: bold; }}
  .loss-badge {{ color: #9C3B1B; font-weight: bold; }}

  .no-data {{ color: #888; font-style: italic; padding: 20px 0; text-align: center; }}
</style>
</head>
<body>

<a href="index.html" class="back-badge">&larr; Menu</a>

<header>
  <div>
    <h1>SAM Shootout — Player History</h1>
    <div class="subtitle">Complete game-by-game history for a single player, all play dates</div>
  </div>
</header>

<div class="controls">
  <label for="playerSelect">Player:</label>
  <select id="playerSelect" onchange="render()"></select>
  <label for="yearSelect">Year:</label>
  <select id="yearSelect" onchange="yearFilter = this.value; renderGames();"></select>
  <button class="refresh-btn" onclick="forceRefresh()">&#8635;&nbsp;Refresh</button>
  <div class="stat-pills" id="statPills"></div>
</div>
<div id="freshness-hint">💡 Tap Refresh anytime to make sure you're seeing the latest data.</div>

<main>
  <section>
    <h2>Career Summary</h2>
    <div id="summaryTable"></div>
  </section>
  <section>
    <div class="sec-head">
      <h2>Game by Game</h2>
    </div>
    <div id="gameTable"></div>
  </section>
</main>

<script>
(function () {{
  const params = new URLSearchParams(location.search);
  if (!params.has('_cb')) {{
    params.set('_cb', Date.now());
    location.replace(location.pathname + '?' + params.toString());
  }}
}})();

const DATA    = {data_json};
const PLAYERS = {players_json};
let yearFilter = "ALL";

const psel = document.getElementById("playerSelect");
PLAYERS.forEach(p => {{
  const opt = document.createElement("option");
  opt.value = p;
  opt.text  = p;
  psel.appendChild(opt);
}});

const preservedPlayer = new URLSearchParams(location.search).get('p');
if (preservedPlayer && PLAYERS.includes(preservedPlayer)) {{
  psel.value = preservedPlayer;
}} else if (PLAYERS.length) {{
  psel.value = PLAYERS[0];
}}

function formatDate(d) {{
  const [y,m,day] = d.split("-");
  const months = ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  const date   = new Date(+y, +m-1, +day);
  const days   = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
  return `${{days[date.getDay()]}} ${{months[+m]}} ${{+day}}, ${{y}}`;
}}

function fmt(n) {{
  if (n === null || n === undefined) return '<span class="zero">—</span>';
  if (n === 0) return '<span class="zero">0</span>';
  return n > 0
    ? `<span class="pos">+${{n}}</span>`
    : `<span class="neg">${{n}}</span>`;
}}

function render() {{
  const player = psel.value;
  const games  = (DATA[player] || []).slice().sort((a,b) => (a.date + a.time).localeCompare(b.date + b.time));

  const wins   = games.filter(g => g.win).length;
  const losses = games.length - wins;
  const adjustedGames = games.filter(g => g.adjusted);
  const entering = games.length ? games[0].cumPre : null;
  const current  = adjustedGames.length ? adjustedGames[adjustedGames.length - 1].post
                   : (games.length ? games[games.length - 1].cumPre : null);
  const totalChange = adjustedGames.length
    ? Math.round(adjustedGames.reduce((sum, g) => sum + g.change, 0))
    : null;

  document.getElementById("statPills").innerHTML =
    `<span class="pill">${{games.length}} Games</span>` +
    `<span class="pill">${{wins}}-${{losses}}</span>`;

  let sh = `<table>
    <thead><tr>
      <th class="left">Player</th>
      <th>Games</th><th>Wins</th><th>Losses</th>
      <th>Entering Rating</th><th>Current Rating</th>
      <th>Career Change</th>
    </tr></thead><tbody>`;
  sh += `<tr>
    <td class="left">${{player}}</td>
    <td>${{games.length}}</td>
    <td class="win-badge">${{wins}}</td>
    <td class="loss-badge">${{losses}}</td>
    <td>${{entering !== null ? entering : '<span class="zero">—</span>'}}</td>
    <td>${{current !== null ? current : '<span class="zero">—</span>'}}</td>
    <td>${{totalChange !== null ? fmt(totalChange) : '<span class="zero">—</span>'}}</td>
  </tr>`;
  sh += "</tbody></table>";
  document.getElementById("summaryTable").innerHTML = games.length ? sh : '<p class="no-data">No games found for this player.</p>';

  const ysel = document.getElementById("yearSelect");
  const years = [...new Set(games.map(g => g.year))].sort();
  const prevYear = yearFilter;
  ysel.innerHTML = "";
  const allYearOpt = document.createElement("option");
  allYearOpt.value = "ALL"; allYearOpt.text = "All years";
  ysel.appendChild(allYearOpt);
  years.forEach(y => {{
    const o = document.createElement("option");
    o.value = y; o.text = y;
    ysel.appendChild(o);
  }});
  yearFilter = years.includes(prevYear) ? prevYear : "ALL";
  ysel.value = yearFilter;

  renderGames();
}}

function renderGames() {{
  const player = psel.value;
  let games = (DATA[player] || []).slice();
  if (yearFilter !== "ALL") games = games.filter(g => g.year === yearFilter);

  // Most recent first
  const sorted = games.sort((a,b) => (b.date + b.time).localeCompare(a.date + a.time));

  let gh = `<table>
    <thead><tr>
      <th>Date</th><th>Time</th><th>Pool</th><th>Shootout</th>
      <th class="left">Partner</th>
      <th class="left">Opponents</th>
      <th>W/L</th><th>Score</th>
      <th>Team Rtg</th><th>Opp Rtg</th><th>Gap</th>
      <th>Pre-Game</th><th>Change</th><th>Post-Game</th>
    </tr></thead><tbody>`;
  sorted.forEach(g => {{
    const ratingCells = g.adjusted
      ? `<td>${{g.pre}}</td><td>${{fmt(g.change)}}</td><td>${{g.post}}</td>`
      : `<td class="unadj-cell" colspan="3" title="Match involved a placeholder (e.g. Den New Player Tryout) -- not counted toward ratings">Unadjusted</td>`;
    gh += `<tr>
      <td>${{formatDate(g.date)}}</td>
      <td>${{g.time}}</td>
      <td>${{g.pool}}</td>
      <td>${{g.shootout}}</td>
      <td class="left">${{g.partner}}</td>
      <td class="left">${{g.opp1}}${{g.opp2 ? " / " + g.opp2 : ""}}</td>
      <td class="${{g.win ? "win-badge" : "loss-badge"}}">${{g.win ? "W" : "L"}}</td>
      <td>${{g.score}}</td>
      <td>${{g.teamRating}}</td>
      <td>${{g.oppRating}}</td>
      <td>${{fmt(g.gap)}}</td>
      ${{ratingCells}}
    </tr>`;
  }});
  gh += "</tbody></table>";
  document.getElementById("gameTable").innerHTML = sorted.length ? gh : '<p class="no-data">No games found for this player/year.</p>';
}}

render();

function forceRefresh() {{
  const params = new URLSearchParams(location.search);
  params.set('_cb', Date.now());
  params.set('p', psel.value);
  location.replace(location.pathname + '?' + params.toString());
}}

setInterval(forceRefresh, 5 * 60 * 1000);
</script>
</body>
</html>
"""

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
OUT_PATH.write_text(html, encoding="utf-8")
print(f"Saved: {OUT_PATH}")
print(f"Players included: {len(players_sorted)}")
