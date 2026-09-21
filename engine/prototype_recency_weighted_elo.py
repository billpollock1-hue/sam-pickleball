"""
Prototype: recency-weighted Elo (time-decay) as a replacement for the
shared-union "no-history-drift" window mechanism.

WHY: collect_recent_match_ids_for_no_history_drift() builds a pool by
UNIONING every qualifying player's own last-60 games, then replays that
whole shared pool from a neutral 1000 baseline. Diagnostic runs showed this
pulls in massive amounts of contamination -- e.g. Lidia Zolnierczyk's replay
pool was 84% games from OUTSIDE her own last-60 window, reaching back to
June 2025; Greg Egli's reached back to September 2024. This is structural,
not a one-off glitch, and it's the direct cause of the instability found in
Peter Barnett's and Lidia Zolnierczyk's ratings.

THIS PROTOTYPE: no window, no union, no cutoff at all. Every game a player
has ever played still contributes to their rating, but each game's
contribution is scaled down the further back in *calendar time* it sits
from the as-of date, using smooth exponential decay (a half-life, not a
cliff). This directly solves the problem you flagged too: a hard "last 60
games" cutoff means 60 games represents 3 weeks for an active player and
9+ months for an inactive one. Time-based decay treats everyone on the same
clock instead of the same game-count.

This is a READ-ONLY prototype. It does not touch build_full_player_log,
the no-history-drift leaderboard, or any production output. It's meant to
be compared side-by-side against the current system so you can judge
whether it's worth adopting -- not to be wired into the pipeline yet.

Usage:
    cd "/Users/billpollock/Documents/SAM Pickleball/sam-pickleball/engine"
    python3 prototype_recency_weighted_elo.py --input "../data/master_history_raw.csv"

Edit HALF_LIFE_DAYS and the CHECKS list below to explore different settings.
"""
import argparse
from pathlib import Path
from collections import defaultdict

import pandas as pd

import pickleball_engine_v2 as eng


# ---------------------------------------------------------------------------
# Tunable: how many days for a game's influence to fall to half weight.
# Smaller = forgets old form faster (more responsive, more volatile).
# Larger  = smoother, slower to reflect real improvement/decline.
# 45 days is roughly 6-7 sessions for an average-frequency player -- a
# starting point for discussion, not a settled answer.
HALF_LIFE_DAYS = 45.0

# Games older than this never fully vanish (avoids a soft "cliff" for very
# old games), but their weight becomes negligible well before this floor.
MIN_WEIGHT_FLOOR = 0.03


def game_recency_decay(days_ago, half_life_days=HALF_LIFE_DAYS, floor=MIN_WEIGHT_FLOOR):
    """Smooth exponential decay by calendar days, not by game count."""
    if days_ago <= 0:
        return 1.0
    weight = 0.5 ** (days_ago / half_life_days)
    return max(floor, weight)


def build_recency_weighted_player_log(raw, as_of, half_life_days=HALF_LIFE_DAYS, floor=MIN_WEIGHT_FLOOR):
    """
    Same relational Elo mechanics as eng.build_full_player_log (result,
    margin, opponent strength all still apply -- nothing about the core
    formula changes) but with each game's K-factor scaled by how far back
    in calendar time it sits from as_of, instead of a hard 60-game window.

    No windowing, no union, no per-date "recent match id" collection step.
    Every game before as_of is processed in one chronological pass.
    """
    as_of = pd.Timestamp(as_of).normalize() + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    scoped = raw[raw["posted_dt"] <= as_of].copy().reset_index(drop=True)

    ratings = defaultdict(lambda: eng.BASE_ELO)
    player_game_count = defaultdict(int)
    player_rows = []

    for match_id, (_, r) in enumerate(scoped.iterrows(), start=1):
        w1, w2 = eng.split_team(r["winning_team"])
        l1, l2 = eng.split_team(r["losing_team"])
        sw, sl = int(r["winning_score"]), int(r["losing_score"])
        include = bool(r["include_in_ratings"])

        snap = {p: ratings[p] for p in [w1, w2, l1, l2]}
        team_win_pre = (snap[w1] + snap[w2]) / 2
        team_lose_pre = (snap[l1] + snap[l2]) / 2
        exp_win = eng.expected(team_win_pre, team_lose_pre)
        exp_lose = 1 - exp_win
        mult = eng.margin_multiplier(sw - sl)

        days_ago = (as_of.normalize() - pd.Timestamp(r["posted_dt"]).normalize()).days
        recency = game_recency_decay(days_ago, half_life_days, floor) if include else 0.0

        if include:
            k_w1 = eng._provisional_k(player_game_count[w1] + 1) * recency
            k_w2 = eng._provisional_k(player_game_count[w2] + 1) * recency
            k_l1 = eng._provisional_k(player_game_count[l1] + 1) * recency
            k_l2 = eng._provisional_k(player_game_count[l2] + 1) * recency
        else:
            k_w1 = k_w2 = k_l1 = k_l2 = 0.0

        d_w1 = round(k_w1 * (1 - exp_win) * mult, 2)
        d_w2 = round(k_w2 * (1 - exp_win) * mult, 2)
        d_l1 = round(k_l1 * (0 - exp_lose) * mult, 2)
        d_l2 = round(k_l2 * (0 - exp_lose) * mult, 2)

        for player, delta in [(w1, d_w1), (w2, d_w2), (l1, d_l1), (l2, d_l2)]:
            pre = snap[player]
            post = round(pre + delta, 2) if include else round(pre, 2)
            player_rows.append({
                "match_id": match_id,
                "posted_dt": r["posted_dt"],
                "player": player,
                "days_ago": days_ago,
                "recency_weight": round(recency, 4),
                "player_pre_rating": round(pre, 2),
                "player_post_rating": post,
                "include_in_ratings": "Yes" if include else "No",
            })

        if include:
            ratings[w1] = round(snap[w1] + d_w1, 2)
            ratings[w2] = round(snap[w2] + d_w2, 2)
            ratings[l1] = round(snap[l1] + d_l1, 2)
            ratings[l2] = round(snap[l2] + d_l2, 2)
            player_game_count[w1] += 1
            player_game_count[w2] += 1
            player_game_count[l1] += 1
            player_game_count[l2] += 1

    return pd.DataFrame(player_rows)


def compare_player(raw, full_player_log, player_name, as_of, half_life_days=HALF_LIFE_DAYS):
    as_of_ts = pd.Timestamp(as_of).normalize()

    # --- current production (shared-union no-history-drift) ---
    recent_match_ids = eng.collect_recent_match_ids_for_no_history_drift(full_player_log, as_of_ts)
    raw_recent = raw.loc[[mid - 1 for mid in recent_match_ids]].copy().reset_index(drop=True)
    prod_log = eng.build_full_player_log(raw_recent)
    prod_rated = prod_log[
        (prod_log["include_in_ratings"] == "Yes")
        & (pd.to_datetime(prod_log["posted_dt"]) <= as_of_ts + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))
    ]
    prod_sub = prod_rated[prod_rated["player"] == player_name].sort_values(["posted_dt", "match_id"])
    prod_rating = float(prod_sub["player_post_rating"].iloc[-1]) if len(prod_sub) else None
    prod_pool_size = len(prod_sub)

    # --- prototype (recency-weighted, no window) ---
    proto_log = build_recency_weighted_player_log(raw, as_of_ts, half_life_days)
    proto_sub = proto_log[
        (proto_log["player"] == player_name) & (proto_log["include_in_ratings"] == "Yes")
    ].sort_values(["posted_dt", "match_id"])
    proto_rating = float(proto_sub["player_post_rating"].iloc[-1]) if len(proto_sub) else None
    effective_games = round(proto_sub["recency_weight"].sum(), 1) if len(proto_sub) else 0.0
    total_games_seen = len(proto_sub)

    print(f"\n{'='*70}")
    print(f"{player_name}  (as of {as_of_ts.date()}, half-life={half_life_days:.0f} days)")
    print(f"{'='*70}")
    print(f"  Current production (shared-union window): {prod_rating}"
          f"  [replay pool size: {prod_pool_size} games]")
    print(f"  Prototype (recency-weighted, no window):  {proto_rating}"
          f"  [effective games: {effective_games} out of {total_games_seen} total games ever played]")
    if prod_rating is not None and proto_rating is not None:
        print(f"  Difference: {round(proto_rating - prod_rating, 1):+}")

    return {"player": player_name, "as_of": str(as_of_ts.date()),
            "production": prod_rating, "prototype": proto_rating,
            "effective_games": effective_games}


def load_raw(input_path):
    raw = pd.read_csv(input_path)
    raw.columns = [c.strip() for c in raw.columns]
    raw["posted_dt"] = pd.to_datetime(raw["posted"], errors="coerce")

    for col in ["winning_team", "losing_team"]:
        raw[col] = [eng.apply_manual_fix(eng.norm(team), dt) for team, dt in zip(raw[col], raw["posted_dt"])]

    raw = raw.drop_duplicates(
        subset=["posted_dt", "winning_team", "losing_team", "winning_score", "losing_score"]
    ).sort_values(
        ["posted_dt", "winning_team", "losing_team", "winning_score", "losing_score"]
    ).reset_index(drop=True)

    raw["exclude_match"] = raw["winning_team"].map(eng.team_has_placeholder) | raw["losing_team"].map(eng.team_has_placeholder)
    raw["include_in_ratings"] = ~raw["exclude_match"]
    return raw


# Edit this list to compare other players/dates. Includes the players from
# the contamination diagnostic plus a stable control (Cary McCormick) whose
# production/prototype numbers should land close together as a sanity check.
CHECKS = [
    ("Peter Barnett", "2026-03-30"),
    ("Lidia Zolnierczyk", "2026-03-31"),
    ("Lidia Zolnierczyk", "2026-04-02"),
    ("Greg Egli", "2026-04-02"),
    ("Toby Orr", "2026-04-02"),
    ("Cary McCormick", "2026-04-02"),
]


def main():
    parser = argparse.ArgumentParser(description="Prototype recency-weighted Elo vs. current production.")
    parser.add_argument("--input", required=True, help="Path to master history CSV")
    parser.add_argument("--half-life", type=float, default=HALF_LIFE_DAYS, help="Decay half-life in days")
    args = parser.parse_args()

    raw = load_raw(Path(args.input))
    full_player_log = eng.build_full_player_log(raw)

    results = []
    for player_name, as_of in CHECKS:
        results.append(compare_player(raw, full_player_log, player_name, as_of, args.half_life))

    print(f"\n{'='*70}\nSummary\n{'='*70}")
    for r in results:
        print(f"  {r['player']:<20} {r['as_of']}  production={r['production']}  "
              f"prototype={r['prototype']}  effective_games={r['effective_games']}")


if __name__ == "__main__":
    main()
