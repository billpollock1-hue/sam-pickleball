"""
Persistent cache for the per-player, per-date "as of" rating grid used by
the point-to-point rating comparison feature.

A past date's snapshot is a fixed historical fact once that date has
passed -- it never changes on its own. Only the newest date's snapshot is
genuinely new each run. So instead of rebuilding the full grid every time
(the ~194s the --with-history flag adds), this caches the whole grid and
only computes new dates each run, appending them.

Invalidation: the cache stores a fingerprint (a hash of all raw game rows
through that date) for EVERY cached date, not just the latest. Fingerprints
are cumulative, so if a given date's fingerprint still matches the current
raw data, every earlier cached date is guaranteed valid too (any change to
older data would have changed this date's fingerprint as well) -- this
monotonic property lets us binary-search backward from the most recent
date to find exactly where the data diverged, rather than discarding the
entire cache on any mismatch. Only dates after that divergence point (plus
any genuinely new dates) get recomputed.

(Prior version stored one fingerprint for "everything through the latest
date" and threw away the whole cache -- all history since 2022 -- on any
mismatch, even a same-day correction adding a missed game. Fixed 2026-09-04
after that cost a 25+ minute full rebuild on a correction affecting one
day's data.)
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


def find_last_valid_date(raw, cached_dates, cached_fingerprints):
    """Binary search cached_dates (sorted ascending) for the latest date
    whose stored fingerprint still matches the current raw data. Returns
    that date string, or None if no cached date is still valid (including
    the case where cached_fingerprints is empty/missing entirely, e.g. a
    cache file from before this per-date scheme existed)."""
    if not cached_dates:
        return None
    lo, hi = 0, len(cached_dates) - 1
    last_valid_idx = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        d = cached_dates[mid]
        expected = cached_fingerprints.get(d)
        if expected is not None and compute_fingerprint(raw, pd.Timestamp(d).date()) == expected:
            last_valid_idx = mid
            lo = mid + 1
        else:
            hi = mid - 1
    if last_valid_idx == -1:
        return None
    return cached_dates[last_valid_idx]


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
    if cache is None:
        cache = {}
    cache.setdefault("dates", [])
    cache.setdefault("ratings", {})
    cache.setdefault("fingerprints", {})

    cached_dates = cache["dates"]
    last_valid_date = find_last_valid_date(raw, cached_dates, cache["fingerprints"])

    if last_valid_date is None:
        if cached_dates:
            print("eod_rating_cache: no cached date's fingerprint still matches -- full rebuild")
        else:
            print("eod_rating_cache: no cache -- full rebuild")
        cache = {"dates": [], "ratings": {}, "fingerprints": {}}
        dates_to_compute = all_dates
    else:
        if last_valid_date != cached_dates[-1]:
            keep_idx = cached_dates.index(last_valid_date)
            discarded = cached_dates[keep_idx + 1:]
            cache["dates"] = cached_dates[: keep_idx + 1]
            for d in discarded:
                cache["ratings"].pop(d, None)
                cache["fingerprints"].pop(d, None)
            print(
                f"eod_rating_cache: data diverged after {last_valid_date} -- "
                f"invalidating {len(discarded)} date(s) after that point"
            )
        cached_dates_set = set(cache["dates"])
        dates_to_compute = [str(d) for d in all_dates if str(d) not in cached_dates_set]
        if dates_to_compute:
            print(
                f"eod_rating_cache: fingerprint matched through {last_valid_date}, "
                f"computing {len(dates_to_compute)} new date(s)"
            )
        else:
            print("eod_rating_cache: fingerprint matched, no new dates -- cache fully up to date")

    for d in dates_to_compute:
        d_date = pd.Timestamp(d).date() if isinstance(d, str) else d
        board_today = board_asof_fn(d_date)
        cache["ratings"][str(d)] = {p: r for p, r in board_today.items() if p in leaderboard_players}
        cache["fingerprints"][str(d)] = compute_fingerprint(raw, d_date)
        cache["dates"].append(str(d))

    cache["dates"] = sorted(set(cache["dates"]))

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
