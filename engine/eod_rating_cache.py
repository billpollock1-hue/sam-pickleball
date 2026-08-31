"""
Persistent cache for the per-player, per-date "as of" rating grid used by
the point-to-point rating comparison feature.

A past date's snapshot is a fixed historical fact once that date has
passed -- it never changes on its own. Only the newest date's snapshot is
genuinely new each run. So instead of rebuilding the full grid every time
(the ~194s the --with-history flag adds), this caches the whole grid and
only computes the one new date each run, appending it.

Invalidation: the cache stores a fingerprint (a hash) of all raw game rows
through the cache's last-covered date. On each run we recompute that same
fingerprint against the CURRENT raw data for that SAME range and compare.
If a historical score gets corrected, the fingerprint for that range
changes and triggers a full rebuild. An ordinary day's new games (appended
after the cached range) never touch that fingerprint, so they never
false-trigger a rebuild.
"""

import hashlib
import json
from pathlib import Path

import pandas as pd


def compute_fingerprint(raw, through_date):
    """Canonical hash of every raw game row with match_day <= through_date."""
    sub = raw[raw["match_day"] <= through_date][
        ["match_day", "winning_team", "losing_team", "winning_score", "losing_score"]
    ].copy()
    sub = sub.sort_values(
        ["match_day", "winning_team", "losing_team", "winning_score", "losing_score"]
    )
    canon = "\n".join(
        f"{r.match_day}|{r.winning_team}|{r.losing_team}|{r.winning_score}|{r.losing_score}"
        for r in sub.itertuples()
    )
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def get_or_update_eod_cache(raw, full_player_log, leaderboard, cache_path, board_asof_fn):
    """
    Returns eod_df (Player + one column per 2026 date, forward-filled rating
    as of that date, current-leaderboard players only) -- same shape as the
    existing --with-history eod_df -- using the cache whenever possible.

    board_asof_fn: a callable date -> {player: rating}, matching the existing
    board_asof() closure already defined in main() (reused, not reimplemented,
    so this stays consistent with build_current_leaderboard()'s own logic).
    """
    cache_path = Path(cache_path)
    # Expanded 2026-08-12 from 2026-only to full history (2022-present) --
    # cheap to do now that this is cached, and "how have I improved since I
    # started" is a more useful comparison than being capped at this year.
    all_dates = sorted(d for d in raw["match_day"].dropna().unique())
    leaderboard_players = set(leaderboard["Player"])

    cache = None
    if cache_path.exists():
        with open(cache_path) as f:
            cache = json.load(f)

    rebuild_needed = True
    if cache is not None and cache.get("dates"):
        cached_through = pd.Timestamp(cache["fingerprint_through_date"]).date()
        current_fp = compute_fingerprint(raw, cached_through)
        if current_fp == cache["fingerprint"]:
            rebuild_needed = False

    if rebuild_needed:
        print("eod_rating_cache: fingerprint mismatch or no cache -- full rebuild")
        cache = {"dates": [], "ratings": {}, "fingerprint": "", "fingerprint_through_date": ""}
        dates_to_compute = all_dates
    else:
        cached_dates_set = set(cache["dates"])
        dates_to_compute = [str(d) for d in all_dates if str(d) not in cached_dates_set]
        if dates_to_compute:
            print(f"eod_rating_cache: fingerprint matched, computing {len(dates_to_compute)} new date(s)")
        else:
            print("eod_rating_cache: fingerprint matched, no new dates -- cache fully up to date")

    for d in dates_to_compute:
        board_today = board_asof_fn(pd.Timestamp(d).date() if isinstance(d, str) else d)
        cache["ratings"][str(d)] = {p: r for p, r in board_today.items() if p in leaderboard_players}
        cache["dates"].append(str(d))

    cache["dates"] = sorted(set(cache["dates"]))
    if cache["dates"]:
        latest = pd.Timestamp(cache["dates"][-1]).date()
        cache["fingerprint_through_date"] = str(latest)
        cache["fingerprint"] = compute_fingerprint(raw, latest)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(cache, f)

    rows = []
    for p in sorted(leaderboard_players):
        last_seen = None
        vals = []
        for d in cache["dates"]:
            if p in cache["ratings"].get(d, {}):
                last_seen = cache["ratings"][d][p]
            vals.append(last_seen if last_seen is not None else "")
        if any(v != "" for v in vals):
            rows.append([p] + vals)

    eod_df = pd.DataFrame(rows, columns=["Player"] + cache["dates"])
    return eod_df
