#!/usr/bin/env python3
"""
Builds a self-contained HTML session viewer with date dropdown.
All data is embedded as JSON — no server required.
"""

import sys, math, json

from collections import defaultdict
from pathlib import Path

import pandas as pd

# Engine lives in the same directory; repo root is the parent
ENGINE_DIR = Path(__file__).resolve().parent
REPO_ROOT  = ENGINE_DIR.parent
sys.path.insert(0, str(ENGINE_DIR))

from pickleball_engine_v2 import (
    BASE_ELO, K_FACTOR, PROVISIONAL_K_START, PROVISIONAL_K_GAMES,
    norm, split_team, apply_manual_fix, team_has_placeholder,
    margin_multiplier, game_position_decay, _provisional_k,
)

DATA_PATH = REPO_ROOT / "data" / "master_history_raw.csv"
OUT_PATH  = REPO_ROOT / "output" / "session_viewer.html"

# ── Load & prepare ────────────────────────────────────────────────────────────
raw = pd.read_csv(DATA_PATH)
raw["posted_dt"] = pd.to_datetime(raw["posted"], errors="coerce")
raw = raw.sort_values("posted_dt").reset_index(drop=True)
raw["winning_team"] = raw.apply(lambda r: apply_manual_fix(r["winning_team"], r["posted_dt"]), axis=1)
raw["losing_team"]  = raw.apply(lambda r: apply_manual_fix(r["losing_team"],  r["posted_dt"]), axis=1)
raw["exclude_match"] = raw.get("exclude_match", False).fillna(False).astype(bool)
raw["include_in_ratings"] = ~(
    raw["winning_team"].apply(team_has_placeholder) |
    raw["losing_team"].apply(team_has_placeholder)  |
    raw["exclude_match"]
)

player_total_games = defaultdict(int)
for _, r in raw.iterrows():
    if r["include_in_ratings"]:
        for p in split_team(r["winning_team"]) + split_team(r["losing_team"]):
            if p:
                player_total_games[p] += 1

# ── Run full Elo history, collect per-date game rows ─────────────────────────
ratings             = defaultdict(lambda: BASE_ELO)
player_game_count   = defaultdict(int)
player_games_window = defaultdict(list)
date_games          = defaultdict(list)   # date_str -> list of game dicts
pool_game_count     = defaultdict(int)    # (date_str, pool) -> games seen so far, for shootout detection

for match_id, (_, r) in enumerate(raw.iterrows(), start=1):
    w1, w2  = split_team(r["winning_team"])
    l1, l2  = split_team(r["losing_team"])
    sw, sl  = int(r["winning_score"]), int(r["losing_score"])
    include = bool(r["include_in_ratings"])
    posted  = r["posted_dt"]

    snap = {}
    for p in [w1, w2, l1, l2]:
        if p:
            snap[p] = ratings[p]

    team_win_pre  = (snap.get(w1, BASE_ELO) + snap.get(w2, BASE_ELO)) / 2
    team_lose_pre = (snap.get(l1, BASE_ELO) + snap.get(l2, BASE_ELO)) / 2
    exp_win = 1 / (1 + 10 ** ((team_lose_pre - team_win_pre) / 400))
    mult    = min(math.log(abs(sw - sl) + 1), 2.0)

    k_w1 = _provisional_k(player_game_count[w1] + 1) if include else 0.0
    k_w2 = _provisional_k(player_game_count[w2] + 1) if include else 0.0
    k_l1 = _provisional_k(player_game_count[l1] + 1) if include else 0.0
    k_l2 = _provisional_k(player_game_count[l2] + 1) if include else 0.0

    def pos(p):
        return min(len(player_games_window[p]) + 1, 60)

    def decay(p):
        return game_position_decay(pos(p), total_games=player_total_games[p]) if include else 1.0

    d_w1 = round(k_w1 * (1 - exp_win) * mult * decay(w1), 2) if w1 else 0
    d_w2 = round(k_w2 * (1 - exp_win) * mult * decay(w2), 2) if w2 else 0
    d_l1 = round(k_l1 * (0 - (1 - exp_win)) * mult * decay(l1), 2) if l1 else 0
    d_l2 = round(k_l2 * (0 - (1 - exp_win)) * mult * decay(l2), 2) if l2 else 0

    if pd.notna(posted) and include:
        date_str = posted.strftime("%Y-%m-%d")
        pool = str(r.get("pool", "")).strip()
        time_str = posted.strftime("%-I:%M %p")

        # Shootout 1 = earliest 3 games on this pool/date; Shootout 2 = the next 3
        pool_game_count[(date_str, pool)] += 1
        shootout = 1 if pool_game_count[(date_str, pool)] <= 3 else 2

        for player, partner, opp1, opp2, is_win, pf, pa, delta in [
            (w1, w2, l1, l2, True,  sw, sl, d_w1),
            (w2, w1, l1, l2, True,  sw, sl, d_w2),
            (l1, l2, w1, w2, False, sl, sw, d_l1),
            (l2, l1, w1, w2, False, sl, sw, d_l2),
        ]:
            if not player:
                continue
            pre  = snap.get(player, BASE_ELO)
            post = round(pre + delta, 2)
            team_pre = (snap.get(player, BASE_ELO) + snap.get(partner, BASE_ELO)) / 2 if partner else snap.get(player, BASE_ELO)
            opp_pre  = (snap.get(opp1, BASE_ELO)   + snap.get(opp2, BASE_ELO))   / 2 if opp2    else snap.get(opp1, BASE_ELO)
            date_games[date_str].append({
                "time":     time_str,
                "pool":     pool,
                "shootout": shootout,
                "player":   player,
                "partner":  partner,
                "opp1":     opp1,
                "opp2":     opp2 or "",
                "win":      is_win,
                "score":    f"{pf}–{pa}",
                "teamRating": round(team_pre),
                "oppRating":  round(opp_pre),
                "gap":        round(team_pre - opp_pre),
                "pre":        round(pre),
                "change":     round(delta),
                "post":       round(post),
            })

    if include:
        for p, d in [(w1, d_w1), (w2, d_w2), (l1, d_l1), (l2, d_l2)]:
            if p:
                ratings[p] = round(snap.get(p, BASE_ELO) + d, 2)
                player_game_count[p] += 1
                player_games_window[p].append(match_id)
                if len(player_games_window[p]) > 60:
                    player_games_window[p] = player_games_window[p][-60:]

dates_sorted = sorted(date_games.keys())
data_json    = json.dumps(date_games)
dates_json   = json.dumps(dates_sorted)
latest_date  = dates_sorted[-1] if dates_sorted else ""

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
  .win-badge  {{ color: #276221; font-weight: bold; }}
  .loss-badge {{ color: #9C3B1B; font-weight: bold; }}

  .no-data {{ color: #888; font-style: italic; padding: 20px 0; text-align: center; }}
</style>
</head>
<body>

<header>
  <div>
    <h1>SAM Shootout — Session Viewer</h1>
    <div class="subtitle">Modified Elo rating changes by play date</div>
  </div>
</header>

<div class="controls">
  <label for="dateSelect">Play Date:</label>
  <select id="dateSelect" onchange="render()"></select>
  <div class="stat-pills" id="statPills"></div>
</div>

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

function formatDate(d) {{
  const [y,m,day] = d.split("-");
  const months = ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  const date   = new Date(+y, +m-1, +day);
  const days   = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
  return `${{days[date.getDay()]}} ${{months[+m]}} ${{+day}}, ${{y}}`;
}}

function fmt(n) {{
  if (n === 0) return '<span class="zero">0</span>';
  return n > 0
    ? `<span class="pos">+${{n}}</span>`
    : `<span class="neg">${{n}}</span>`;
}}

function render() {{
  const date   = sel.value;
  const games  = DATA[date] || [];

  // ── Player summary ──────────────────────────────────────────────────────
  const players = {{}};
  games.forEach(g => {{
    if (!players[g.player]) players[g.player] = {{
      player: g.player, games: 0, wins: 0, losses: 0,
      startPre: g.pre, endPost: g.post, totalChange: 0, oppRatings: []
    }};
    const p = players[g.player];
    p.games++;
    g.win ? p.wins++ : p.losses++;
    p.endPost     = g.post;
    p.totalChange = Math.round(p.totalChange + g.change);
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
    sh += `<tr>
      <td class="left">${{p.player}}</td>
      <td>${{p.games}}</td>
      <td class="win-badge">${{p.wins}}</td>
      <td class="loss-badge">${{p.losses}}</td>
      <td>${{p.startPre}}</td>
      <td>${{p.endPost}}</td>
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
      <td>${{g.pre}}</td>
      <td>${{fmt(g.change)}}</td>
      <td>${{g.post}}</td>
    </tr>`;
  }});
  gh += "</tbody></table>";
  document.getElementById("gameTable").innerHTML = sorted.length ? gh : '<p class="no-data">No data for this date.</p>';
}}

render();
</script>
</body>
</html>
"""

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
OUT_PATH.write_text(html, encoding="utf-8")
print(f"Saved: {OUT_PATH}")
print(f"Dates included: {len(date_games)}")
print(f"Latest date: {latest_date}")
