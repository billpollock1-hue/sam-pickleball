#!/usr/bin/env python3
"""
Builds a self-contained HTML session viewer with date dropdown.
All data is embedded as JSON — no server required.
Ratings sourced from Player_Game_Log in pickleball_model_latest.xlsx
to ensure consistency with leaderboard and court assignments viewer.
"""

import sys, json
from pathlib import Path
from collections import defaultdict
import pandas as pd

ENGINE_DIR = Path(__file__).resolve().parent
REPO_ROOT  = ENGINE_DIR.parent

MODEL_PATH = REPO_ROOT / "output" / "pickleball_model_latest.xlsx"
OUT_PATH   = REPO_ROOT / "output" / "session_viewer.html"

# ── Load Player_Game_Log ──────────────────────────────────────────────────────
pgl = pd.read_excel(MODEL_PATH, sheet_name="Player_Game_Log")
pgl["posted_dt"] = pd.to_datetime(pgl["posted_dt"])
pgl["date_str"]  = pgl["posted_dt"].dt.strftime("%Y-%m-%d")
pgl["time_str"]  = pgl["posted_dt"].dt.strftime("%H:%M")

# Show every game that was actually played -- including matches involving
# a placeholder ("Den New Player Tryout" or similar) and games that fell
# outside a player's own no-history-drift window but stayed in because a
# different participant's shorter window still carried the match (see the
# July 13, 2026 Cary McCormick / Peter Barnett investigation: a match is
# only pulled into the "recent" replay if ANY of its 4 players still has
# it in their own last-60-games window, which silently showed some
# players' games on a date but not their partners'/opponents' on the
# exact same match).
#
# Per-row rating display now falls back in two steps rather than a hard
# filter:
#   1. include_in_ratings == "Yes" and nhd_pre/post present -> use those
#      (leaderboard-consistent, last-60-games basis).
#   2. include_in_ratings == "Yes" but nhd is NaN (aged out of this
#      player's own window, but the match still counted) -> fall back to
#      the full cumulative player_pre/post_rating rather than hiding the
#      game.
#   3. include_in_ratings == "No" (placeholder/tryout match) -> show the
#      game itself, but with no rating figures -- flagged "adjusted": false
#      so the front end can label it "Unadjusted" instead of a number.

# ── Build date_games dict ─────────────────────────────────────────────────────
date_games = defaultdict(list)

for _, r in pgl.sort_values("posted_dt").iterrows():
    is_win  = bool(r["is_win"])
    pf      = int(r["pf"]) if pd.notna(r.get("pf")) else 0
    pa      = int(r["pa"]) if pd.notna(r.get("pa")) else 0
    adjusted = str(r.get("include_in_ratings", "No")).strip() == "Yes"

    if adjusted and pd.notna(r.get("nhd_pre_rating")):
        pre    = round(float(r["nhd_pre_rating"]))
        post   = round(float(r["nhd_post_rating"]))
        change = round(float(r["nhd_post_rating"]) - float(r["nhd_pre_rating"]), 1)
    elif adjusted:
        # Counted toward ratings, but this date has aged out of this
        # player's own last-60-games window -- fall back to the full
        # cumulative rating rather than hiding a game that genuinely
        # affected their rating.
        pre    = round(float(r["player_pre_rating"]))
        post   = round(float(r["player_post_rating"]))
        change = round(float(r["player_post_rating"]) - float(r["player_pre_rating"]), 1)
    else:
        # Placeholder/tryout match -- ratings intentionally not adjusted.
        pre = post = change = None
    team    = round(float(r["team_pre_rating"]))
    opp     = round(float(r["opp_team_pre_rating"]))
    gap     = round(team - opp)
    opp2    = r.get("opp2", "")
    opp2    = "" if pd.isna(opp2) else str(opp2)
    partner = r.get("partner", "")
    partner = "" if pd.isna(partner) else str(partner)

    # Score always from player perspective: pf = points for, pa = points against
    score = f"{pf}\u2013{pa}"

    date_games[r["date_str"]].append({
        "time":       r["time_str"],
        "pool":       str(r.get("pool", "") or ""),
        "shootout":   int(r.get("shootout", 1) or 1),
        "player":     str(r["player"]),
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
        # Always populated, even on unadjusted (tryout) games, since the
        # engine snapshots player_pre_rating before checking whether the
        # match counts -- this is a player's real rating walking into this
        # specific game. Used as a fallback in the summary table when a
        # player had NO adjusted games that day (e.g. every one of their
        # matches involved a placeholder), so the viewer can still show
        # what rating they actually had, rather than a blank dash.
        "cumPre":     round(float(r["player_pre_rating"])),
    })

dates_sorted = sorted(date_games.keys())
data_json    = json.dumps(date_games)
dates_json   = json.dumps(dates_sorted)
latest_date  = dates_sorted[-1] if dates_sorted else ""

print(f"Dates included: {len(dates_sorted)}")
print(f"Latest date: {latest_date}")

# ── Build HTML ────────────────────────────────────────────────────────────────
html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SAM Shootout — Session Viewer</title>
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
    <h1>SAM Shootout — Session Viewer</h1>
    <div class="subtitle">Modified Elo rating changes by play date</div>
  </div>
</header>

<div class="controls">
  <label for="dateSelect">Play Date:</label>
  <select id="dateSelect" onchange="render()"></select>
  <button class="refresh-btn" onclick="forceRefresh()">&#8635;&nbsp;Refresh</button>
  <div class="stat-pills" id="statPills"></div>
</div>
<div id="freshness-hint">💡 Tap Refresh anytime to make sure you're seeing the latest data.</div>

<main>
  <section>
    <h2>Player Summary</h2>
    <div id="summaryTable"></div>
  </section>
  <section>
    <div class="sec-head">
      <h2>Game by Game</h2>
      <label for="shootoutSelect">Shootout:</label>
      <select id="shootoutSelect" onchange="shootoutFilter = this.value; renderGames();"></select>
      <label for="poolSelect">Pool:</label>
      <select id="poolSelect" onchange="poolFilter = this.value; renderGames();"></select>
      <label for="playerSelect">Player:</label>
      <select id="playerSelect" onchange="playerFilter = this.value; renderGames();"></select>
    </div>
    <div id="gameTable"></div>
  </section>
</main>

<script>
// ── Freshness: force a genuine network fetch on every real navigation to
// this page, bypassing any browser/CDN cache. If this load doesn't already
// carry our cache-bust marker, immediately redirect to a URL that does --
// GitHub Pages' CDN (and browsers) cache by full URL including query
// string, so a unique timestamp guarantees a cache miss.
(function () {{
  const params = new URLSearchParams(location.search);
  if (!params.has('_cb')) {{
    params.set('_cb', Date.now());
    location.replace(location.pathname + '?' + params.toString());
  }}
}})();

const DATA   = {data_json};
const DATES  = {dates_json};
const LATEST = "{latest_date}";
let playerFilter = "ALL";
let poolFilter = "ALL";
let shootoutFilter = "ALL";

// Populate date dropdown (newest first)
const sel = document.getElementById("dateSelect");
[...DATES].reverse().forEach(d => {{
  const opt = document.createElement("option");
  opt.value = d;
  opt.text  = formatDate(d);
  sel.appendChild(opt);
}});
sel.value = LATEST;

// Restore a manually-selected date carried over from a periodic auto-reload
// (see setInterval below), if that date still has data -- otherwise the
// reload would silently snap back to LATEST while someone is actively
// reviewing an older session.
const preservedDate = new URLSearchParams(location.search).get('d');
if (preservedDate && DATES.includes(preservedDate)) {{
  sel.value = preservedDate;
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
  const date   = sel.value;
  const games  = DATA[date] || [];

  // ── Player summary ──────────────────────────────────────────────────────
  // Games/Wins/Losses count every game played, including matches involving
  // a placeholder (e.g. "Den New Player Tryout"). Rating figures (Start/End/
  // Total Change) only ever come from adjusted games -- an unadjusted game
  // contributes to the box score but not to the rating tally, since it
  // never affected ratings in the first place.
  const players = {{}};
  games.forEach(g => {{
    if (!players[g.player]) players[g.player] = {{
      player: g.player, games: 0, wins: 0, losses: 0,
      startPre: null, endPost: null, totalChange: 0, oppRatings: [],
      hasUnadjusted: false, enteringRating: null
    }};
    const p = players[g.player];
    p.games++;
    g.win ? p.wins++ : p.losses++;
    // cumPre is populated on every game (adjusted or not) -- capture the
    // first one seen for this player today as their real rating walking
    // into the day, for use as a fallback if none of today's games ended
    // up counting toward ratings.
    if (p.enteringRating === null) p.enteringRating = g.cumPre;
    if (g.adjusted) {{
      if (p.startPre === null) p.startPre = g.pre;
      p.endPost     = g.post;
      p.totalChange = Math.round(p.totalChange + g.change);
    }} else {{
      p.hasUnadjusted = true;
    }}
    p.oppRatings.push(g.oppRating);
  }});

  const summaryRows = Object.values(players)
    .sort((a,b) => b.totalChange - a.totalChange);

  // Stat pills
  const totalGames = games.length / 4;  // 4 rows per game
  const uniquePlayers = summaryRows.length;
  document.getElementById("statPills").innerHTML =
    `<span class="pill">${{uniquePlayers}} Players</span>` +
    `<span class="pill">${{Math.round(totalGames)}} Games</span>`;

  // Summary table
  let sh = `<table>
    <thead><tr>
      <th class="left">Player</th>
      <th>Games</th><th>Wins</th><th>Losses</th>
      <th>Start Rating</th><th>End Rating</th>
      <th>Total Change</th><th>Avg Opp Rating</th>
    </tr></thead><tbody>`;
  summaryRows.forEach(p => {{
    const avgOpp = Math.round(p.oppRatings.reduce((a,b)=>a+b,0)/p.oppRatings.length);
    const nameCell = p.hasUnadjusted
      ? `${{p.player}} <span class="unadj-note" title="Includes a game with a placeholder (e.g. Den New Player Tryout) -- not counted toward ratings">*</span>`
      : p.player;
    // If no game today counted toward ratings, fall back to the player's
    // real entering rating (unchanged all day) instead of a blank dash --
    // tagged distinctly since it reflects no games affecting it today.
    const startCell = p.startPre !== null
      ? p.startPre
      : `<span class="unadj-cell" title="Entering rating -- no games today counted toward ratings">~${{p.enteringRating}}</span>`;
    const endCell = p.endPost !== null
      ? p.endPost
      : `<span class="unadj-cell" title="Unchanged -- no games today counted toward ratings">~${{p.enteringRating}}</span>`;
    sh += `<tr>
      <td class="left">${{nameCell}}</td>
      <td>${{p.games}}</td>
      <td class="win-badge">${{p.wins}}</td>
      <td class="loss-badge">${{p.losses}}</td>
      <td>${{startCell}}</td>
      <td>${{endCell}}</td>
      <td>${{fmt(p.totalChange)}}</td>
      <td>${{avgOpp}}</td>
    </tr>`;
  }});
  sh += "</tbody></table>";
  document.getElementById("summaryTable").innerHTML = summaryRows.length ? sh : '<p class="no-data">No data for this date.</p>';

  // ── Player filter dropdown ─────────────────────────────────────────────
  // Rebuild for this date; keep the current selection if that player played
  const psel = document.getElementById("playerSelect");
  const names = [...new Set(games.map(g => g.player))].sort();
  const prev = playerFilter;
  psel.innerHTML = "";
  const allOpt = document.createElement("option");
  allOpt.value = "ALL"; allOpt.text = "All players";
  psel.appendChild(allOpt);
  names.forEach(n => {{
    const o = document.createElement("option");
    o.value = n; o.text = n;
    psel.appendChild(o);
  }});
  playerFilter = names.includes(prev) ? prev : "ALL";
  psel.value = playerFilter;

  // ── Pool filter dropdown ─────────────────────────────────────────────
  const poolSel = document.getElementById("poolSelect");
  const pools = [...new Set(games.map(g => g.pool))].sort();
  const prevPool = poolFilter;
  poolSel.innerHTML = "";
  const allPoolOpt = document.createElement("option");
  allPoolOpt.value = "ALL"; allPoolOpt.text = "All pools";
  poolSel.appendChild(allPoolOpt);
  pools.forEach(pl => {{
    const o = document.createElement("option");
    o.value = pl; o.text = pl;
    poolSel.appendChild(o);
  }});
  poolFilter = pools.includes(prevPool) ? prevPool : "ALL";
  poolSel.value = poolFilter;

  // ── Shootout filter dropdown ────────────────────────────────────────
  const shSel = document.getElementById("shootoutSelect");
  const prevSh = shootoutFilter;
  shSel.innerHTML = "";
  const allShOpt = document.createElement("option");
  allShOpt.value = "ALL"; allShOpt.text = "Both shootouts";
  shSel.appendChild(allShOpt);
  [1,2].forEach(sNum => {{
    const o = document.createElement("option");
    o.value = String(sNum); o.text = "Shootout " + sNum;
    shSel.appendChild(o);
  }});
  shootoutFilter = ["ALL","1","2"].includes(prevSh) ? prevSh : "ALL";
  shSel.value = shootoutFilter;

  renderGames();
}}

function renderGames() {{
  const date  = sel.value;
  const games = DATA[date] || [];
  let view = games;
  if (playerFilter !== "ALL") view = view.filter(g => g.player === playerFilter);
  if (poolFilter !== "ALL") view = view.filter(g => g.pool === poolFilter);
  if (shootoutFilter !== "ALL") view = view.filter(g => String(g.shootout) === shootoutFilter);

  // Sort by time
  const sorted = [...view].sort((a,b) => {{
    // Parse time for sort
    const t = s => {{ const [h,m,ap] = [s.slice(0,s.indexOf(":")), s.slice(s.indexOf(":")+1,s.indexOf(" ")), s.slice(-2)];
                      return (+h % 12 + (ap==="PM"?12:0))*60 + +m; }};
    return t(a.time) - t(b.time) || a.pool.localeCompare(b.pool) || a.player.localeCompare(b.player);
  }});

  let gh = `<table>
    <thead><tr>
      <th>Time</th><th>Pool</th><th>Shootout</th>
      <th class="left">Player</th><th class="left">Partner</th>
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
      <td>${{g.time}}</td>
      <td>${{g.pool}}</td>
      <td>${{g.shootout}}</td>
      <td class="left">${{g.player}}</td>
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
  document.getElementById("gameTable").innerHTML = sorted.length ? gh : '<p class="no-data">No data for this date.</p>';
}}

render();

// Forces a genuine network fetch bypassing any cache, carrying the current
// date selection forward so it isn't lost -- used both by the manual
// Refresh button and the periodic timer below.
function forceRefresh() {{
  const params = new URLSearchParams(location.search);
  params.set('_cb', Date.now());
  params.set('d', sel.value);
  location.replace(location.pathname + '?' + params.toString());
}}

// Periodic freshness re-check for tabs left open a while.
setInterval(forceRefresh, 5 * 60 * 1000);
</script>
</body>
</html>
"""

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
OUT_PATH.write_text(html, encoding="utf-8")
print(f"Saved: {OUT_PATH}")
print(f"Dates included: {len(date_games)}")
print(f"Latest date: {latest_date}")
