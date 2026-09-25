#!/usr/bin/env python3
"""
Bear Count — a fun leaderboard tracking "bears" earned during shootouts
since 2026-08-24, per Bill's rules:

  1. Pickle bear: any time a team wins a game 11-0, each player on the
     winning team earns a bear.
  2. Shootout bear (woman): if a woman finishes on top of her 4-player
     pool (most wins across the 3 round-robin games; ties broken by
     summed point differential), she earns a bear -- regardless of how
     many of the 3 games she won.
  3. Shootout bear (man): if a man finishes on top of his pool by
     winning all 3 games, he earns a bear. A man leading his pool with
     only 2 wins does NOT earn a bear (but is still tracked in the
     "Leader (2W)" column below).

A pool is a (play date, shootout #, pool name) group of 4 players who
play a 3-game round robin -- this is what Bill calls "their shootout"
when he says a player was the top finisher. Every pool has exactly 4
players and 6 total player-wins across its 3 games, so by pigeonhole
the top win count in any pool is always 2 or 3 (never fewer) -- hence
those are the only two "Leader" columns needed.

Reads the same workbook the rest of the site is built from, so run
after the model build (same place build_leaderboard_html.py runs).
"""

import json
from pathlib import Path

import pandas as pd

ENGINE_DIR = Path(__file__).resolve().parent
REPO_ROOT = ENGINE_DIR.parent
XLSX_PATH = REPO_ROOT / "output" / "pickleball_model_latest.xlsx"
GENDER_PATH = REPO_ROOT / "data" / "player_gender.csv"
OVERRIDES_PATH = REPO_ROOT / "data" / "shootout_leader_overrides.csv"
OUT_PATH = REPO_ROOT / "output" / "bear_count.html"

BEAR_START_DATE = pd.Timestamp("2026-08-24")

# ── Load data ──────────────────────────────────────────────────────
gl = pd.read_excel(XLSX_PATH, sheet_name="Player_Game_Log")
gl["posted_dt"] = pd.to_datetime(gl["posted_dt"])
gl = gl[(gl["posted_dt"] >= BEAR_START_DATE) & (gl["include_in_ratings"] == "Yes")].copy()
gl["play_date"] = gl["posted_dt"].dt.strftime("%Y-%m-%d")

gender_df = pd.read_csv(GENDER_PATH)
gender_map = dict(zip(gender_df["player"], gender_df["gender"]))
low_confidence = set(gender_df[gender_df.get("confidence", "high") == "low"]["player"])

# ── Manual overrides for genuine wins+margin ties ───────────────────────
# Den decides pool 1st place by something we can't derive from our own
# win/margin data (apparently a coin flip when truly tied on both). When
# our tiebreak can't separate the tied players, we can't safely credit
# any of them with a shootout bear unless Bill has confirmed who Den
# actually declared the winner -- so an unresolved tie gets NO bear
# rather than crediting everyone who was tied (which was the bug: e.g.
# on 2026-09-16 Jill Peterson and Tonya Carroll were both wrongly
# credited alongside Neal Whitson, the actual winner).
def _pool_key(play_date, shootout, pool):
    return (str(play_date), int(shootout), str(pool))

overrides_map = {}
if OVERRIDES_PATH.exists():
    ov_df = pd.read_csv(OVERRIDES_PATH, dtype=str).fillna("")
    for _, r in ov_df.iterrows():
        winner = r["winner"].strip()
        if winner:
            overrides_map[_pool_key(r["play_date"], r["shootout"], r["pool"])] = winner

if gl.empty:
    print(f"No rated games on/after {BEAR_START_DATE.date()} -- nothing to build.")
    raise SystemExit(0)

data_through = gl["posted_dt"].max().strftime("%B %-d, %Y")

# ── Pickle bears: 11-0 wins ─────────────────────────────────────────────
gl["pickle_bear"] = (gl["is_win"] == 1) & (gl["pf"] == 11) & (gl["pa"] == 0)

# ── Pool-level leader determination ─────────────────────────────────────
pool_keys = ["play_date", "shootout", "pool"]
pool_player_stats = (
    gl.groupby(pool_keys + ["player"])
    .agg(wins=("is_win", "sum"), margin_sum=("margin", "sum"))
    .reset_index()
)

leader_rows = []
unresolved_ties = []
for key, grp in pool_player_stats.groupby(pool_keys):
    max_wins = grp["wins"].max()
    top = grp[grp["wins"] == max_wins]
    max_margin = top["margin_sum"].max()
    tied = top[top["margin_sum"] == max_margin]
    if len(tied) == 1:
        leaders = tied
    else:
        winner = overrides_map.get(_pool_key(*key))
        if winner is not None and winner in tied["player"].values:
            leaders = tied[tied["player"] == winner]
        else:
            unresolved_ties.append((key, list(tied["player"])))
            leaders = tied.iloc[0:0]
    for _, lr in leaders.iterrows():
        leader_rows.append({
            "play_date": key[0], "shootout": key[1], "pool": key[2],
            "player": lr["player"], "leader_wins": int(lr["wins"]),
        })
leaders_df = pd.DataFrame(leader_rows)

if unresolved_ties:
    print(f"WARNING: {len(unresolved_ties)} pool(s) have an unresolved wins+margin tie "
          f"-- no shootout bear awarded until resolved in {OVERRIDES_PATH.relative_to(REPO_ROOT)}:")
    for key, players in unresolved_ties:
        print(f"  {key[0]} shootout {key[1]} {key[2]}: {' / '.join(players)}")

    # Self-maintaining: append any newly-discovered tie to the overrides
    # file (blank winner) so it shows up as a pending item on the admin
    # panel's Shootout Ties page without needing a code change here.
    # Existing rows (including already-resolved ones) are left untouched.
    known_keys = set(overrides_map.keys())
    if OVERRIDES_PATH.exists():
        existing_df = pd.read_csv(OVERRIDES_PATH, dtype=str).fillna("")
        known_keys |= {_pool_key(r["play_date"], r["shootout"], r["pool"]) for _, r in existing_df.iterrows()}
    else:
        existing_df = pd.DataFrame(columns=["play_date", "shootout", "pool", "tied_candidates", "winner"])

    new_rows = []
    for key, players in unresolved_ties:
        if _pool_key(*key) not in known_keys:
            new_rows.append({
                "play_date": key[0], "shootout": key[1], "pool": key[2],
                "tied_candidates": " / ".join(players), "winner": "",
            })
    if new_rows:
        combined = pd.concat([existing_df, pd.DataFrame(new_rows)], ignore_index=True)
        combined.to_csv(OVERRIDES_PATH, index=False)
        print(f"Added {len(new_rows)} newly-discovered tie(s) to {OVERRIDES_PATH.relative_to(REPO_ROOT)}.")

def gender_bear(row):
    g = gender_map.get(row["player"])
    if g == "F":
        return True
    if g == "M" and row["leader_wins"] == 3:
        return True
    return False

if not leaders_df.empty:
    leaders_df["shootout_bear"] = leaders_df.apply(gender_bear, axis=1)

# ── Per-player aggregation ──────────────────────────────────────────────
players = sorted(gl["player"].unique())
rows_out = []
for p in players:
    pg = gl[gl["player"] == p]
    play_dates = pg["play_date"].nunique()
    pickles_won = int(pg["is_win"].sum())
    pickles_lost = int(len(pg) - pickles_won)
    pickle_bears = int(pg["pickle_bear"].sum())

    plead = leaders_df[leaders_df["player"] == p] if not leaders_df.empty else pd.DataFrame()
    leader_2 = int((plead["leader_wins"] == 2).sum())
    leader_3 = int((plead["leader_wins"] == 3).sum())
    shootout_bears = int(plead["shootout_bear"].sum()) if not plead.empty else 0

    total_bears = pickle_bears + shootout_bears

    # Pool-by-pool detail for the click-through modal
    detail = []
    for key, grp in gl[gl["player"] == p].groupby(pool_keys):
        wins = int(grp["is_win"].sum())
        pbears_here = int(grp["pickle_bear"].sum())
        is_leader_row = plead[
            (plead["play_date"] == key[0]) & (plead["shootout"] == key[1]) & (plead["pool"] == key[2])
        ] if not plead.empty else pd.DataFrame()
        was_leader = not is_leader_row.empty
        sbear = bool(is_leader_row["shootout_bear"].iloc[0]) if was_leader else False
        detail.append({
            "date": key[0], "shootout": int(key[1]), "pool": str(key[2]),
            "wins": wins, "pickle_bears": pbears_here,
            "leader": was_leader, "shootout_bear": sbear,
        })
    detail.sort(key=lambda d: (d["date"], d["shootout"], d["pool"]))

    rows_out.append({
        "player": p,
        "gender": gender_map.get(p, ""),
        "low_conf": p in low_confidence,
        "play_dates": play_dates,
        "pickles_won": pickles_won,
        "pickles_lost": pickles_lost,
        "leader_2": leader_2,
        "leader_3": leader_3,
        "pickle_bears": pickle_bears,
        "shootout_bears": shootout_bears,
        "total_bears": total_bears,
        "detail": detail,
    })

rows_out.sort(key=lambda r: (-r["total_bears"], -r["shootout_bears"], -r["pickle_bears"], r["player"]))

player_detail = {r["player"]: r["detail"] for r in rows_out}
player_detail_json = json.dumps(player_detail, separators=(",", ":"))

# ── Build table rows ────────────────────────────────────────────────────
table_rows = ""
for i, r in enumerate(rows_out, start=1):
    flag = ' <span class="lc" title="Gender inferred from name -- needs review">?</span>' if r["low_conf"] else ""
    table_rows += f"""
      <tr>
        <td class="rk">{i}</td>
        <td class="nm">{r['player']}{flag} <span class="bear-log-link" data-player="{r['player']}" title="Bear pool log">📋</span></td>
        <td>{r['play_dates']}</td>
        <td>{r['leader_2']}</td>
        <td>{r['leader_3']}</td>
        <td>{r['pickle_bears']}</td>
        <td>{r['shootout_bears']}</td>
        <td class="tot">{r['total_bears']} <span class="bear-tally">{'🐻' * r['total_bears']}</span></td>
      </tr>"""

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SAM Bear Count</title>
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

  .page {{ max-width: 1040px; margin: 0 auto; padding: 14px 10px 40px;
           display: flex; gap: 18px; align-items: flex-start; flex-wrap: wrap; }}

  .wrap {{ flex: 1 1 640px; min-width: 0; order: 2; }}

  .back-badge {{ position: fixed; top: 10px; left: 10px; z-index: 1000;
                 background: #1F4E79; color: #fff; font-size: 12px;
                 padding: 6px 12px; border-radius: 6px; text-decoration: none;
                 box-shadow: 0 1px 4px rgba(0,0,0,0.2); border: none; cursor: pointer; }}
  .back-badge:hover {{ background: #163a5c; }}
  #freshness-hint {{ padding: 6px 16px; font-size: 11px; color: #888;
                     background: #fafafa; border-bottom: 1px solid #e8edf3; text-align: center; }}

  /* ── Rules decoder (left panel) ── */
  .decoder {{ flex: 1 1 240px; max-width: 260px; order: 1; }}
  .dc-card {{ background: #fff; border-radius: 10px; box-shadow: 0 1px 4px rgba(31,78,121,0.10);
              padding: 14px 14px 16px; }}
  .dc-title {{ font-size: 14px; font-weight: 700; color: var(--blue-dark); margin-bottom: 10px; }}
  .dc-row {{ display: flex; align-items: flex-start; gap: 8px; margin-bottom: 9px; font-size: 12px; line-height: 1.4; }}
  .dc-icon {{ flex-shrink: 0; width: 20px; text-align: center; }}

  table {{ width: 100%; border-collapse: collapse; background: #fff;
           border-radius: 10px; overflow: hidden; box-shadow: 0 1px 4px rgba(31,78,121,0.10); }}
  th {{
    background: var(--blue-mid); color: #fff; padding: 9px 6px;
    font-size: 11.5px; text-align: center; position: sticky; top: 0;
  }}
  th.nm {{ text-align: left; }}
  td {{ padding: 8px 6px; text-align: center; font-size: 13.5px;
        border-bottom: 1px solid #e8edf3; white-space: nowrap; }}
  td.rk {{ color: #8a97a8; font-size: 13px; width: 30px; }}
  td.nm {{ text-align: left; font-weight: 600; }}
  td.tot {{ font-weight: bold; color: var(--blue-dark); white-space: normal; }}
  .bear-tally {{ font-size: 11px; letter-spacing: -1px; }}
  tr:nth-child(even) td {{ background: #f2f6fb; }}
  .lc {{ color: #c9a84c; font-weight: 700; cursor: help; }}

  /* ── Trophy win-count badge (pool-log modal) ── */
  .tr-badge {{ position: relative; display: inline-block; line-height: 1; }}
  .tr-badge .tr-num {{
    position: absolute; right: -4px; bottom: -3px;
    background: var(--blue-dark); color: #fff;
    font-size: 8px; font-weight: 700; line-height: 1;
    border-radius: 50%; width: 10px; height: 10px;
    display: flex; align-items: center; justify-content: center;
    box-shadow: 0 0 0 1.5px #fff;
  }}

  .foot {{ margin-top: 12px; font-size: 12px; color: #8a97a8; text-align: center; line-height: 1.6; }}
  .foot a {{ color: var(--blue-mid); }}

  .bear-log-link {{ cursor: pointer; font-size: 12px; opacity: 0.55; }}
  .bear-log-link:hover {{ opacity: 1; }}

  .modal-overlay {{ position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 2000;
                     display: flex; align-items: center; justify-content: center; padding: 16px; }}
  .modal-box {{ background: #fff; border-radius: 10px; max-width: 560px; width: 100%;
                max-height: 84vh; overflow-y: auto; box-shadow: 0 4px 24px rgba(0,0,0,0.25); }}
  .modal-header {{ display: flex; align-items: center; justify-content: space-between;
                    padding: 14px 18px; border-bottom: 1px solid #e8edf3;
                    position: sticky; top: 0; background: #fff; }}
  .modal-header h3 {{ font-size: 15px; color: var(--blue-dark); }}
  .modal-close {{ background: none; border: none; font-size: 22px; line-height: 1;
                   color: #8a97a8; cursor: pointer; padding: 0 4px; }}
  .modal-close:hover {{ color: var(--blue-dark); }}
  .modal-body {{ padding: 12px 18px 18px; }}
  .modal-body .no-data {{ font-size: 13px; color: #8a97a8; text-align: center; padding: 20px 0; }}

  .hist-table {{ width: 100%; border-collapse: collapse; font-size: 12.5px; box-shadow: none; }}
  .hist-table th {{ background: var(--blue-light); color: var(--blue-dark); position: static;
                     font-size: 11px; padding: 6px 5px; }}
  .hist-table td {{ padding: 6px 5px; font-size: 12.5px; white-space: nowrap; }}

  @media (max-width: 430px) {{
    td {{ font-size: 12.5px; padding: 7px 4px; }}
    th {{ font-size: 10.5px; }}
    .hist-table th, .hist-table td {{ font-size: 11px; padding: 5px 3px; }}
  }}
  @media (max-width: 900px) {{
    .decoder {{ max-width: none; flex-basis: 100%; order: 1; }}
    .wrap {{ order: 2; }}
  }}
</style>
</head>
<body>

<a href="index.html" class="back-badge">&larr; Menu</a>
<button class="back-badge" style="left:96px;" onclick="forceRefresh()">&#8635;&nbsp;Refresh</button>

<header>
  <h1>🐻 SAM Bear Count</h1>
  <p>Bears earned since Aug 24, 2026 &middot; through {data_through}</p>
  <p style="font-style:italic; font-weight:bold; color:#ff6f61; font-size:14px; margin-top:8px;">Bear totals exclude bears earned for International attire/language and "treat" bears.</p>
</header>
<div id="freshness-hint">💡 Tap Refresh anytime to make sure you're seeing the latest data.</div>

<div class="page">
  <div class="decoder">
    <div class="dc-card">
      <div class="dc-title">How to Earn a Bear</div>
      <div class="dc-row"><span class="dc-icon">🥒</span><span><b>Pickle bear</b> — win a game 11-0. Every player on the winning team earns one.</span></div>
      <div class="dc-row"><span class="dc-icon">🏆</span><span><b>Shootout bear (women)</b> — finish on top of your 4-player pool (most game wins, ties broken by point differential). Any win count qualifies.</span></div>
      <div class="dc-row"><span class="dc-icon">🏆</span><span><b>Shootout bear (men)</b> — finish on top of your pool by winning all 3 games. Leading with only 2 wins does not earn a bear (although it is tracked).</span></div>
    </div>
  </div>

  <div class="wrap">
    <table>
      <thead>
        <tr>
          <th>#</th><th class="nm">Player</th><th>Play<br>Dates</th>
          <th>Leader<br>(2W)</th><th>Leader<br>(3W)</th><th>Pickle<br>Bears</th><th>Shootout<br>Bears</th><th>Total<br>Bears</th>
        </tr>
      </thead>
      <tbody id="body">{table_rows}
      </tbody>
    </table>
    <p class="foot">
      Bears counted since Aug 24, 2026, from rated games only.<br>
      Leader (2W)/(3W) = number of pools where this player finished on top with 2 or 3 wins (informational -- not every "Leader" earns a bear; see rules).<br>
      Tap the 📋 next to a player's name for their pool-by-pool bear log.<br>
      <a href="index.html">All charts &amp; tools</a> &middot; updated after every play date
    </p>
  </div>
</div>

<div id="historyModal" class="modal-overlay" style="display:none;">
  <div class="modal-box">
    <div class="modal-header">
      <h3 id="historyModalTitle">Player Bear Log</h3>
      <button class="modal-close" onclick="closeHistory()">&times;</button>
    </div>
    <div id="historyModalBody" class="modal-body"></div>
  </div>
</div>

<script>
(function () {{
  const params = new URLSearchParams(location.search);
  if (!params.has('_cb')) {{
    params.set('_cb', Date.now());
    location.replace(location.pathname + '?' + params.toString());
  }}
}})();

function forceRefresh() {{
  const params = new URLSearchParams(location.search);
  params.set('_cb', Date.now());
  location.replace(location.pathname + '?' + params.toString());
}}

setInterval(forceRefresh, 5 * 60 * 1000);

// PLAYER_DETAIL: {{ playerName: [ {{date, shootout, pool, wins, pickle_bears,
// leader, shootout_bear}}, ... ] }} -- one entry per pool the player
// appeared in since Aug 24, 2026, most recent last as built.
const PLAYER_DETAIL = {player_detail_json};

function showHistory(name) {{
  const rows = (PLAYER_DETAIL[name] || []).slice().reverse();
  document.getElementById('historyModalTitle').textContent = name + ' — Bear Log';

  const body = document.getElementById('historyModalBody');
  if (rows.length === 0) {{
    body.innerHTML = '<p class="no-data">No pool data available yet.</p>';
  }} else {{
    let h = `<table class="hist-table"><thead><tr>
      <th>Date</th><th>Sht</th><th>Pool</th><th>Wins</th><th>Pool Leader</th><th>Bears</th>
    </tr></thead><tbody>`;
    rows.forEach(r => {{
      let bears = '';
      if (r.pickle_bears > 0) bears += '🥒'.repeat(r.pickle_bears);
      if (r.shootout_bear) bears += `<span class="tr-badge">🏆<span class="tr-num">${{r.wins}}</span></span>`;
      if (!bears) bears = '—';
      h += `<tr>
        <td>${{r.date}}</td>
        <td>${{r.shootout}}</td>
        <td>${{r.pool}}</td>
        <td>${{r.wins}}/3</td>
        <td>${{r.leader ? 'Yes' : '—'}}</td>
        <td>${{bears}}</td>
      </tr>`;
    }});
    h += '</tbody></table>';
    body.innerHTML = h;
  }}
  document.getElementById('historyModal').style.display = 'flex';
}}

function closeHistory() {{
  document.getElementById('historyModal').style.display = 'none';
}}

document.getElementById('body').addEventListener('click', (e) => {{
  const link = e.target.closest('.bear-log-link');
  if (link) showHistory(link.dataset.player);
}});

document.getElementById('historyModal').addEventListener('click', (e) => {{
  if (e.target.id === 'historyModal') closeHistory();
}});
document.addEventListener('keydown', (e) => {{
  if (e.key === 'Escape') closeHistory();
}});
</script>
</body>
</html>
"""

OUT_PATH.write_text(html, encoding="utf-8")
print(f"Saved: {OUT_PATH} ({len(rows_out)} players, through {data_through})")
print(f"Pools processed: {len(pool_player_stats.groupby(pool_keys))}")
