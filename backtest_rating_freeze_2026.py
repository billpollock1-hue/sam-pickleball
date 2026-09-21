#!/usr/bin/env python3
"""
Backtest: does the full-history rating (frozen as of 1/1/2026) already
predict 2026 performance, or does building it on history back to 2022
leave a persistent, measurable gap for long-tenured players?

Method: for every player with at least one rated game BEFORE 2026-01-01,
freeze their rating at that pre-2026 level (a player's player_pre_rating
on their first 2026 game equals their player_post_rating from their last
pre-2026 game, by construction of the sequential engine -- no recompute
needed, it's already sitting in Player_Game_Log). Score every 2026 game
using ONLY that frozen rating (never the live, continuously-updating one)
to get an expected win probability, then compare against what actually
happened.

If actual tracks frozen-expected closely -- including for players with
history back to 2022/2023 -- that's real evidence the full-history rating
had already caught up entering the year, not still being dragged down by
stale history. A persistent positive residual (actual > frozen-expected)
for specific players is the concrete signature of a real catch-up lag,
and is worth chasing as a real finding rather than dismissing.

Games where any of the 4 participants has no pre-2026 history (a player
who joined in 2026) are dropped -- the frozen-baseline question doesn't
apply to them.
"""
import numpy as np
import pandas as pd

MODEL_OUTPUT = "output/pickleball_model_latest.xlsx"
FREEZE_DATE = pd.Timestamp("2026-01-01")
LONG_TENURE_CUTOFF = pd.Timestamp("2023-01-01")  # "history back to 2022/2023" per the raised concern
MIN_GAMES_2026 = 5  # drop tiny per-player samples -- too noisy to read


def main():
    gl = pd.read_excel(MODEL_OUTPUT, sheet_name="Player_Game_Log")
    gl = gl[gl["include_in_ratings"] == "Yes"].copy()
    gl["posted_dt"] = pd.to_datetime(gl["posted_dt"])
    gl = gl.sort_values(["posted_dt", "match_id"])

    pre_2026 = gl[gl["posted_dt"] < FREEZE_DATE]
    post_2026 = gl[gl["posted_dt"] >= FREEZE_DATE]

    if pre_2026.empty or post_2026.empty:
        print("Not enough data on either side of the freeze date -- aborting.")
        return

    players_with_pre2026_history = set(pre_2026["player"].unique())
    first_seen = gl.groupby("player")["posted_dt"].min()

    frozen = (
        post_2026[post_2026["player"].isin(players_with_pre2026_history)]
        .sort_values(["posted_dt", "match_id"])
        .groupby("player")["player_pre_rating"]
        .first()
    )
    frozen_map = frozen.to_dict()

    rows = []
    dropped_games = 0
    for _, r in post_2026.iterrows():
        p, partner, o1, o2 = r["player"], r["partner"], r["opp1"], r["opp2"]
        if any(x not in frozen_map for x in (p, partner, o1, o2)):
            dropped_games += 1
            continue
        team_r = (frozen_map[p] + frozen_map[partner]) / 2
        opp_r = (frozen_map[o1] + frozen_map[o2]) / 2
        exp_frozen = 1 / (1 + 10 ** ((opp_r - team_r) / 400))
        rows.append({
            "player": p,
            "posted_dt": r["posted_dt"],
            "is_win": r["is_win"],
            "expected_frozen": exp_frozen,
        })

    scored = pd.DataFrame(rows)
    print(f"Scored {len(scored)} player-games in 2026 against 1/1/2026-frozen ratings "
          f"({dropped_games} player-games dropped -- a participant had no pre-2026 history).")

    # --- Pooled / aggregate result ---
    n = len(scored)
    actual = scored["is_win"].mean()
    expected = scored["expected_frozen"].mean()
    print(f"\n=== POOLED (all qualifying players, {n} player-games) ===")
    print(f"Actual win%:            {actual:.1%}")
    print(f"1/1/26-frozen expected: {expected:.1%}")
    print(f"Residual (actual-exp):  {actual - expected:+.1%}")

    # --- Per-player ---
    per_player = scored.groupby("player").agg(
        games=("is_win", "size"),
        actual_win_pct=("is_win", "mean"),
        expected_frozen_pct=("expected_frozen", "mean"),
    )
    per_player["residual"] = per_player["actual_win_pct"] - per_player["expected_frozen_pct"]

    def z_score(name):
        sub = scored[scored["player"] == name]
        diffs = sub["is_win"] - sub["expected_frozen"]
        var = (sub["expected_frozen"] * (1 - sub["expected_frozen"])).sum()
        return diffs.sum() / np.sqrt(var) if var > 0 else np.nan

    per_player["z"] = [z_score(name) for name in per_player.index]
    per_player["first_seen"] = per_player.index.map(first_seen).date
    per_player["long_tenured"] = per_player.index.map(first_seen) < LONG_TENURE_CUTOFF

    per_player = per_player[per_player["games"] >= MIN_GAMES_2026]
    per_player = per_player.sort_values("residual", ascending=False)

    print(f"\n=== PER-PLAYER (>={MIN_GAMES_2026} games in 2026, sorted by residual, "
          f"{len(per_player)} players) ===")
    with pd.option_context("display.max_rows", None, "display.width", 160):
        print(per_player[["games", "actual_win_pct", "expected_frozen_pct", "residual", "z",
                           "first_seen", "long_tenured"]]
              .round({"actual_win_pct": 3, "expected_frozen_pct": 3, "residual": 3, "z": 2}))

    print(f"\n=== Long-tenured subgroup only (first game before {LONG_TENURE_CUTOFF.date()}) ===")
    lt = per_player[per_player["long_tenured"]]
    print(f"Players: {len(lt)}   Mean residual: {lt['residual'].mean():+.3f}   "
          f"Players with |z| > 1.96: {(lt['z'].abs() > 1.96).sum()} "
          f"(expect ~{len(lt) * 0.05:.1f} by chance alone at this sample size)")

    out_path = "output/rating_freeze_backtest_2026.csv"
    per_player.to_csv(out_path)
    print(f"\nSaved full per-player table to {out_path}")


if __name__ == "__main__":
    main()
