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
from pickleball_engine_v2 import PLACEHOLDERS

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
        "pf":         pf,
        "pa":         pa,
        "teamRating": int(team),
        "oppRating":  int(opp),
        "gap":        int(gap),
        "pre":        pre,
        "change":     change,
        "post":       post,
        "adjusted":   adjusted,
        "cumPre":     round(float(r["player_pre_rating"])),
    })

def _is_placeholder(name):
    return name.strip().lower() in PLACEHOLDERS

players_sorted = sorted(p for p in player_games.keys() if not _is_placeholder(p))
data_json      = json.dumps(player_games)
players_json   = json.dumps(players_sorted)

# Leaderboard-only subset for the "current leaderboard players" toggle default
lb_sheet = pd.read_excel(MODEL_PATH, sheet_name="Leaderboard")
leaderboard_players = set(lb_sheet["Player"].astype(str))
leaderboard_players_sorted = sorted(p for p in players_sorted if p in leaderboard_players)
leaderboard_players_json = json.dumps(leaderboard_players_sorted)

print(f"Players included: {len(players_sorted)} ({len(leaderboard_players_sorted)} on current leaderboard)")

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
  .sec-head {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
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
  th.sortable {{ cursor: pointer; user-select: none; }}
  th.sortable:hover {{ background: #245f8f; }}
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
  <label class="lb-toggle"><input type="checkbox" id="lbOnlyToggle" checked onchange="lbOnly = this.checked; populatePlayerSelect(); render();"> Leaderboard players only</label>
  <label for="yearSelect">Year:</label>
  <select id="yearSelect" onchange="yearFilter = this.value; renderGames();"></select>
  <button class="refresh-btn" onclick="forceRefresh()">&#8635;&nbsp;Refresh</button>
  <div class="stat-pills" id="statPills"></div>
</div>
<div id="freshness-hint">💡 Tap Refresh anytime to make sure you're seeing the latest data. Click a column header to sort by it.</div>

<main>
  <section>
    <h2>Career Summary</h2>
    <div id="summaryTable"></div>
  </section>
  <section>
    <h2>Record by Partner</h2>
    <div id="partnerTable"></div>
  </section>
  <section>
    <h2>Record by Opponent</h2>
    <div id="opponentTable"></div>
  </section>
  <section>
    <div class="sec-head">
      <h2>Game by Game</h2>
      <label for="partnerSelect">Partner:</label>
      <select id="partnerSelect" onchange="partnerFilter = this.value; applyGameFilters();"></select>
      <label for="opponentSelect">Opponent:</label>
      <select id="opponentSelect" onchange="opponentFilter = this.value; applyGameFilters();"></select>
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
const LEADERBOARD_PLAYERS = {leaderboard_players_json};
let lbOnly = true;
let yearFilter     = "ALL";
let partnerFilter  = "ALL";
let opponentFilter = "ALL";

let currentGameRows     = [];
let currentPartnerRows  = [];
let currentOpponentRows = [];

const sortState = {{
  game:     {{ key: "date",  dir: -1 }},
  partner:  {{ key: "games", dir: -1 }},
  opponent: {{ key: "games", dir: -1 }}
}};

const psel = document.getElementById("playerSelect");

function populatePlayerSelect() {{
  const prev = psel.value;
  const list = lbOnly ? LEADERBOARD_PLAYERS : PLAYERS;
  psel.innerHTML = "";
  list.forEach(p => {{
    const opt = document.createElement("option");
    opt.value = p;
    opt.text  = p;
    psel.appendChild(opt);
  }});
  const keepIdx = list.indexOf(prev);
  psel.selectedIndex = keepIdx >= 0 ? keepIdx : 0;
}}
populatePlayerSelect();

const preservedPlayer = new URLSearchParams(location.search).get('p');
if (preservedPlayer && PLAYERS.includes(preservedPlayer)) {{
  // A preserved player from a forced refresh may not be in the current
  // list (e.g. leaderboard-only view but the preserved player isn't on
  // the leaderboard) -- fall back to leaderboard-only in that case rather
  // than silently switching the toggle off.
  if (!(lbOnly ? LEADERBOARD_PLAYERS : PLAYERS).includes(preservedPlayer)) {{
    lbOnly = false;
    document.getElementById("lbOnlyToggle").checked = false;
    populatePlayerSelect();
  }}
  psel.value = preservedPlayer;
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

// ── Generic sortable table renderer ─────────────────────────────────────────
// columns: [{{ key, label, align, sortVal(row), render(row) }}]
function renderTable(containerId, tableKey, columns, rows) {{
  const state = sortState[tableKey];
  const col   = columns.find(c => c.key === state.key) || columns[0];
  const sorted = [...rows].sort((a,b) => {{
    const av = col.sortVal(a);
    const bv = col.sortVal(b);
    if (av < bv) return -1 * state.dir;
    if (av > bv) return  1 * state.dir;
    return 0;
  }});

  let h = "<table><thead><tr>";
  columns.forEach(c => {{
    const arrow = state.key === c.key ? (state.dir === 1 ? " \u25b2" : " \u25bc") : "";
    const cls = c.align === "left" ? "left sortable" : "sortable";
    h += `<th class="${{cls}}" onclick="setSort('${{tableKey}}','${{c.key}}')">${{c.label}}${{arrow}}</th>`;
  }});
  h += "</tr></thead><tbody>";
  sorted.forEach(row => {{
    h += "<tr>";
    columns.forEach(c => {{
      const cls = c.align === "left" ? "left" : "";
      h += `<td class="${{cls}}">${{c.render(row)}}</td>`;
    }});
    h += "</tr>";
  }});
  h += "</tbody></table>";
  document.getElementById(containerId).innerHTML = sorted.length ? h : '<p class="no-data">No data for this selection.</p>';
}}

function setSort(tableKey, key) {{
  const state = sortState[tableKey];
  if (state.key === key) {{
    state.dir = -state.dir;
  }} else {{
    state.key = key;
    state.dir = -1;
  }}
  if (tableKey === "game")      renderTable("gameTable", "game", gameColumns, currentGameRows);
  if (tableKey === "partner")   renderTable("partnerTable", "partner", partnerColumns, currentPartnerRows);
  if (tableKey === "opponent")  renderTable("opponentTable", "opponent", opponentColumns, currentOpponentRows);
}}

// ── Column definitions ──────────────────────────────────────────────────────
const partnerColumns = [
  {{ key: "name",      label: "Partner",            align: "left",   sortVal: r => r.name,      render: r => r.name }},
  {{ key: "games",     label: "Games",               align: "center", sortVal: r => r.games,     render: r => r.games }},
  {{ key: "wins",      label: "Wins",                align: "center", sortVal: r => r.wins,      render: r => `<span class="win-badge">${{r.wins}}</span>` }},
  {{ key: "losses",    label: "Losses",              align: "center", sortVal: r => r.losses,    render: r => `<span class="loss-badge">${{r.losses}}</span>` }},
  {{ key: "winPct",    label: "Win %",               align: "center", sortVal: r => r.winPct,    render: r => `${{r.winPct}}%` }},
  {{ key: "pf",        label: "Points For",          align: "center", sortVal: r => r.pf,        render: r => r.pf }},
  {{ key: "pa",        label: "Points Against",      align: "center", sortVal: r => r.pa,        render: r => r.pa }},
  {{ key: "netMargin", label: "Net Margin",          align: "center", sortVal: r => r.pf - r.pa, render: r => fmt(r.pf - r.pa) }},
  {{ key: "avgMargin", label: "Avg Margin",          align: "center", sortVal: r => r.avgMargin, render: r => fmt(r.avgMargin) }},
  {{ key: "avgChange", label: "Avg Rating Change",   align: "center", sortVal: r => r.avgChange === null ? -Infinity : r.avgChange, render: r => r.avgChange !== null ? fmt(r.avgChange) : '<span class="zero">—</span>' }}
];
const opponentColumns = partnerColumns.map(c => c.key === "name" ? {{ ...c, label: "Opponent" }} : c);

const gameColumns = [
  {{ key: "date",       label: "Date",       align: "center", sortVal: g => g.date + g.time,          render: g => formatDate(g.date) }},
  {{ key: "time",       label: "Time",       align: "center", sortVal: g => g.time,                    render: g => g.time }},
  {{ key: "pool",       label: "Pool",       align: "center", sortVal: g => g.pool,                    render: g => g.pool }},
  {{ key: "shootout",   label: "Shootout",   align: "center", sortVal: g => g.shootout,                render: g => g.shootout }},
  {{ key: "partner",    label: "Partner",    align: "left",   sortVal: g => g.partner,                 render: g => g.partner }},
  {{ key: "opponents",  label: "Opponents",  align: "left",   sortVal: g => g.opp1 + g.opp2,           render: g => g.opp1 + (g.opp2 ? " / " + g.opp2 : "") }},
  {{ key: "win",        label: "W/L",        align: "center", sortVal: g => g.win ? 1 : 0,             render: g => `<span class="${{g.win ? "win-badge" : "loss-badge"}}">${{g.win ? "W" : "L"}}</span>` }},
  {{ key: "score",      label: "Score",      align: "center", sortVal: g => g.pf - g.pa,               render: g => g.score }},
  {{ key: "teamRating", label: "Team Rtg",   align: "center", sortVal: g => g.teamRating,              render: g => g.teamRating }},
  {{ key: "oppRating",  label: "Opp Rtg",    align: "center", sortVal: g => g.oppRating,               render: g => g.oppRating }},
  {{ key: "gap",        label: "Gap",        align: "center", sortVal: g => g.gap,                     render: g => fmt(g.gap) }},
  {{ key: "pre",        label: "Pre-Game",   align: "center", sortVal: g => g.pre === null ? -Infinity : g.pre,       render: g => g.adjusted ? g.pre : '<span class="unadj-cell">Unadj.</span>' }},
  {{ key: "change",     label: "Change",     align: "center", sortVal: g => g.change === null ? -Infinity : g.change, render: g => g.adjusted ? fmt(g.change) : '<span class="unadj-cell">—</span>' }},
  {{ key: "post",       label: "Post-Game",  align: "center", sortVal: g => g.post === null ? -Infinity : g.post,     render: g => g.adjusted ? g.post : '<span class="unadj-cell">—</span>' }}
];

// ── Partner/Opponent summary breakdown (respects Year filter only) ─────────
function renderBreakdowns(games) {{
  const partners = {{}};
  games.forEach(g => {{
    if (!g.partner) return;
    if (!partners[g.partner]) partners[g.partner] = {{ name: g.partner, games: 0, wins: 0, losses: 0, pf: 0, pa: 0, changeSum: 0, adjustedCount: 0 }};
    const p = partners[g.partner];
    p.games++;
    g.win ? p.wins++ : p.losses++;
    p.pf += g.pf;
    p.pa += g.pa;
    if (g.adjusted) {{ p.changeSum += g.change; p.adjustedCount++; }}
  }});
  currentPartnerRows = Object.values(partners)
    .filter(p => !lbOnly || LEADERBOARD_PLAYERS.includes(p.name))
    .map(p => ({{
      ...p,
      winPct: p.games ? Math.round((p.wins / p.games) * 100) : 0,
      avgMargin: p.games ? Math.round(((p.pf - p.pa) / p.games) * 10) / 10 : 0,
      avgChange: p.adjustedCount ? Math.round((p.changeSum / p.adjustedCount) * 10) / 10 : null
    }}));
  renderTable("partnerTable", "partner", partnerColumns, currentPartnerRows);

  const opponents = {{}};
  games.forEach(g => {{
    [g.opp1, g.opp2].forEach(oppName => {{
      if (!oppName) return;
      if (!opponents[oppName]) opponents[oppName] = {{ name: oppName, games: 0, wins: 0, losses: 0, pf: 0, pa: 0, changeSum: 0, adjustedCount: 0 }};
      const o = opponents[oppName];
      o.games++;
      g.win ? o.wins++ : o.losses++;
      o.pf += g.pf;
      o.pa += g.pa;
      if (g.adjusted) {{ o.changeSum += g.change; o.adjustedCount++; }}
    }});
  }});
  currentOpponentRows = Object.values(opponents)
    .filter(o => !lbOnly || LEADERBOARD_PLAYERS.includes(o.name))
    .map(o => ({{
      ...o,
      winPct: o.games ? Math.round((o.wins / o.games) * 100) : 0,
      avgMargin: o.games ? Math.round(((o.pf - o.pa) / o.games) * 10) / 10 : 0,
      avgChange: o.adjustedCount ? Math.round((o.changeSum / o.adjustedCount) * 10) / 10 : null
    }}));
  renderTable("opponentTable", "opponent", opponentColumns, currentOpponentRows);
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

  const totalPF = games.reduce((sum, g) => sum + g.pf, 0);
  const totalPA = games.reduce((sum, g) => sum + g.pa, 0);
  const netMargin = totalPF - totalPA;

  document.getElementById("statPills").innerHTML =
    `<span class="pill">${{games.length}} Games</span>` +
    `<span class="pill">${{wins}}-${{losses}}</span>` +
    `<span class="pill">Margin ${{netMargin >= 0 ? "+" : ""}}${{netMargin}}</span>`;

  const winPct = games.length ? Math.round((wins / games.length) * 100) : 0;
  const avgMargin = games.length ? Math.round((netMargin / games.length) * 10) / 10 : 0;
  const avgChange = adjustedGames.length ? Math.round((totalChange / adjustedGames.length) * 10) / 10 : null;

  let sh = `<table>
    <thead><tr>
      <th class="left">Player</th>
      <th>Games</th><th>Wins</th><th>Losses</th><th>Win %</th>
      <th>Entering Rating</th><th>Current Rating</v>
      <th>Career Change</th><th>Avg Rating Change</th>
      <th>Points For</th><th>Points Against</th><th>Net Margin</th><th>Avg Margin</th>
    </tr></thead><tbody>`;
  sh += `<tr>
    <td class="left">${{player}}</td>
    <td>${{games.length}}</td>
    <td class="win-badge">${{wins}}</td>
    <td class="loss-badge">${{losses}}</td>
    <td>${{winPct}}%</td>
    <td>${{entering !== null ? entering : '<span class="zero">—</span>'}}</td>
    <td>${{current !== null ? current : '<span class="zero">—</span>'}}</td>
    <td>${{totalChange !== null ? fmt(totalChange) : '<span class="zero">—</span>'}}</td>
    <td>${{avgChange !== null ? fmt(avgChange) : '<span class="zero">—</span>'}}</td>
    <td>${{totalPF}}</td>
    <td>${{totalPA}}</td>
    <td>${{fmt(netMargin)}}</td>
    <td>${{fmt(avgMargin)}}</td>
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

// Recomputes the Year-filtered game set (used for the breakdown tables and
// to repopulate the Partner/Opponent filter dropdown lists), then applies
// the Partner/Opponent filter on top of that for the Game-by-Game table.
function renderGames() {{
  const player = psel.value;
  let games = (DATA[player] || []).slice();
  if (yearFilter !== "ALL") games = games.filter(g => g.year === yearFilter);

  renderBreakdowns(games);

  const psel2 = document.getElementById("partnerSelect");
  const partnerNames = [...new Set(games.map(g => g.partner).filter(Boolean))].sort();
  const prevPartner = partnerFilter;
  psel2.innerHTML = "";
  const allPartnerOpt = document.createElement("option");
  allPartnerOpt.value = "ALL"; allPartnerOpt.text = "All partners";
  psel2.appendChild(allPartnerOpt);
  partnerNames.forEach(n => {{
    const o = document.createElement("option");
    o.value = n; o.text = n;
    psel2.appendChild(o);
  }});
  partnerFilter = partnerNames.includes(prevPartner) ? prevPartner : "ALL";
  psel2.value = partnerFilter;

  const osel = document.getElementById("opponentSelect");
  const opponentNames = [...new Set(games.flatMap(g => [g.opp1, g.opp2]).filter(Boolean))].sort();
  const prevOpponent = opponentFilter;
  osel.innerHTML = "";
  const allOpponentOpt = document.createElement("option");
  allOpponentOpt.value = "ALL"; allOpponentOpt.text = "All opponents";
  osel.appendChild(allOpponentOpt);
  opponentNames.forEach(n => {{
    const o = document.createElement("option");
    o.value = n; o.text = n;
    osel.appendChild(o);
  }});
  opponentFilter = opponentNames.includes(prevOpponent) ? prevOpponent : "ALL";
  osel.value = opponentFilter;

  applyGameFilters(games);
}}

// Applies the Partner/Opponent filter (in addition to the Year filter
// already reflected in `games`) and renders the Game-by-Game table.
function applyGameFilters(games) {{
  if (!games) {{
    const player = psel.value;
    games = (DATA[player] || []).slice();
    if (yearFilter !== "ALL") games = games.filter(g => g.year === yearFilter);
  }}
  let filtered = games;
  if (partnerFilter !== "ALL") filtered = filtered.filter(g => g.partner === partnerFilter);
  if (opponentFilter !== "ALL") filtered = filtered.filter(g => g.opp1 === opponentFilter || g.opp2 === opponentFilter);

  currentGameRows = filtered;
  renderTable("gameTable", "game", gameColumns, currentGameRows);
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
