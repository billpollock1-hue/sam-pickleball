import sys

import pandas as pd
from pathlib import Path

MASTER_FILE = Path("data/master_history_raw.csv")
UPDATE_FILE = Path("data/latest_scrape.csv")

LATEST_STANDINGS_FILE = Path("data/latest_scrape_standings.csv")
POOL_STANDINGS_FILE = Path("data/pool_standings.csv")


def _norm_shootout(x):
    """'1', '1.0', 1, 1.0 all -> '1' so master- and update-file dtypes compare cleanly."""
    try:
        return str(int(float(x)))
    except (TypeError, ValueError):
        return str(x).strip()


def find_touched_pools(update):
    """(play_date, shootout, pool) keys for every pool this scrape run touched."""
    upd = update.copy()
    upd["posted_dt"] = pd.to_datetime(upd["posted"], errors="coerce")
    upd["play_date"] = upd["posted_dt"].dt.date
    upd["shootout_norm"] = upd["shootout"].map(_norm_shootout)
    keys = (
        upd.dropna(subset=["play_date"])[["play_date", "shootout_norm", "pool"]]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    )
    return set(keys)


def validate_pools(df, touched_pools):
    """
    Sanity-check every (play_date, shootout, pool) group this scrape run
    touched, before it's allowed to land in master_history_raw.csv.

    Added after a real incident (2026-09-25): a Vaadin virtual-grid stale
    read in scrape.js produced a game row whose winner/loser were swapped
    and whose score was actually borrowed from a *different* game in the
    same pool. The one thing that gave it away: the corrupted row shared
    an exact `posted` timestamp AND score with a real row in that pool --
    something that should never happen, since Den logs each game's
    completion to the minute and two truly distinct games essentially
    never finish in the identical minute with the identical score.

    Returns a list of human-readable problem strings; empty = all clear.
    This can't prove a winner/loser swap by itself (a swap can still look
    like a structurally valid game), but it catches the mechanical
    signature the swap leaves behind, plus a couple of other cheap sanity
    checks that would catch other classes of misread.
    """
    problems = []
    work = df.copy()
    work["posted_dt"] = pd.to_datetime(work["posted"], errors="coerce")
    work["play_date"] = work["posted_dt"].dt.date
    work["shootout_norm"] = work["shootout"].map(_norm_shootout)

    for play_date, shootout, pool in sorted(touched_pools, key=lambda k: (str(k[0]), k[1], k[2])):
        grp = work[
            (work["play_date"] == play_date)
            & (work["shootout_norm"] == shootout)
            & (work["pool"] == pool)
        ]
        if grp.empty:
            continue

        label = f"{play_date} shootout {shootout} {pool}"

        # 1. Two games in the same pool sharing an exact posted timestamp
        #    is normal on its own (Den's display only has minute
        #    resolution, and two games can genuinely finish in the same
        #    minute) -- confirmed real (2026-09-25, Pool 1: two correct,
        #    distinct games both display 6:35 AM). But two games sharing
        #    BOTH the identical timestamp AND the identical score is a
        #    different story: that's exactly the signature the real
        #    incident left behind (a corrupted row's score was borrowed
        #    from a different game in the same pool that happened to post
        #    at the same minute), and is essentially impossible to occur
        #    legitimately in a 3-game pool.
        dupe_key = grp["posted"].astype(str) + "|" + grp["winning_score"].astype(str) + "-" + grp["losing_score"].astype(str)
        dupe_counts = dupe_key.value_counts()
        for key, n in dupe_counts[dupe_counts > 1].items():
            ts, score = key.split("|", 1)
            problems.append(
                f"{label}: {n} games share both the identical posted timestamp '{ts}' "
                f"AND the identical score {score} -- this is the signature of a stale/"
                f"cross-contaminated grid read (one row's score borrowed from another "
                f"game in the pool), not a real coincidence."
            )

        # 2. Score sanity: winner must be 11, loser 0-10.
        for _, row in grp.iterrows():
            try:
                w = int(float(row["winning_score"]))
                l = int(float(row["losing_score"]))
            except (TypeError, ValueError):
                continue
            if w != 11 or not (0 <= l <= 10):
                problems.append(
                    f"{label}: game posted {row['posted']} has an invalid score "
                    f"{w}-{l} (winner should be 11, loser 0-10)."
                )

        # 3. A pool should never involve more than 4 unique players.
        players = set()
        for col in ("winning_team", "losing_team"):
            for team in grp[col].dropna():
                players.update(p.strip() for p in str(team).split("/") if p.strip())
        if len(players) > 4:
            problems.append(
                f"{label}: {len(players)} unique players appear across its games "
                f"({', '.join(sorted(players))}) -- a pool should have exactly 4."
            )

    return problems


def merge_pool_standings():
    """
    Merge this run's scraped Round Robin Stats (data/latest_scrape_standings.csv,
    written by scrape.js's View Event pass) into the durable
    data/pool_standings.csv. Best-effort and independent of the main master
    history merge above -- a missing/empty standings file just means no new
    standings to merge (e.g. the View Event pass failed or found nothing),
    never an error.

    A pool's standings only replace what's already on file for that
    (play_date, shootout, pool) once the new data passes a light sanity
    check: exactly one row per rank 1..N with no gaps or repeats (Den's
    grid should always come back complete or not at all). A pool that
    fails this check is skipped -- keeping whatever was already on file
    (if anything) -- rather than writing a partial/garbled standings.
    """
    if not LATEST_STANDINGS_FILE.exists():
        return
    new_standings = pd.read_csv(LATEST_STANDINGS_FILE)
    if new_standings.empty:
        return

    new_standings["shootout"] = new_standings["shootout"].map(_norm_shootout)

    if POOL_STANDINGS_FILE.exists():
        existing = pd.read_csv(POOL_STANDINGS_FILE)
        existing["shootout"] = existing["shootout"].map(_norm_shootout)
    else:
        existing = pd.DataFrame(columns=["play_date", "shootout", "pool", "rank", "player", "wins", "losses", "diff"])

    group_cols = ["play_date", "shootout", "pool"]
    valid_groups = []
    for key, grp in new_standings.groupby(group_cols):
        ranks = sorted(grp["rank"].tolist())
        if ranks == list(range(1, len(ranks) + 1)):
            valid_groups.append(key)
        else:
            print(f"  ⚠ Skipping standings for {key[0]} shootout {key[1]} {key[2]}: "
                  f"ranks {ranks} are not a clean 1..N sequence -- keeping prior data, if any.")

    if not valid_groups:
        return

    valid_mask = new_standings.set_index(group_cols).index.isin(valid_groups)
    new_standings = new_standings[valid_mask]

    # Replace: drop any existing rows for the (play_date, shootout, pool)
    # keys this run just re-supplied valid data for, then append the new
    # rows -- so a rescrape always overwrites rather than accumulating
    # duplicates.
    touched = set(new_standings[group_cols].itertuples(index=False, name=None))
    if not existing.empty:
        keep_mask = ~existing[group_cols].apply(tuple, axis=1).isin(touched)
        existing = existing[keep_mask]

    combined = pd.concat([existing, new_standings], ignore_index=True)
    combined = combined.sort_values(["play_date", "shootout", "pool", "rank"]).reset_index(drop=True)
    combined.to_csv(POOL_STANDINGS_FILE, index=False)
    print(f"Pool standings updated: {len(new_standings)} row(s) merged across {len(valid_groups)} pool(s).")


print("Loading files...")

master = pd.read_csv(MASTER_FILE)
update = pd.read_csv(UPDATE_FILE)

before_master = len(master)
update_rows = len(update)

print(f"Master rows before merge: {before_master}")
print(f"Update rows: {update_rows}")

# Combine master history with latest scrape
df = pd.concat([master, update], ignore_index=True)

# Normalize key columns so duplicate detection is reliable
key_cols = [
    "posted",
    "winning_team",
    "winning_score",
    "losing_team",
    "losing_score",
    "game_type",
    "pool",
]

for col in key_cols:
    if col in df.columns:
        df[col] = df[col].astype(str).str.strip()

# Remove duplicate games based on actual game identity
before = len(df)

df = df.drop_duplicates(subset=key_cols)

after = len(df)

print(f"Duplicates removed: {before - after}")

# Normalize exclude_match column for rating engine use only
if "exclude_match" not in df.columns:
    df["exclude_match"] = False

df["exclude_match"] = (
    df["exclude_match"]
    .fillna(False)
    .astype(str)
    .str.strip()
    .str.lower()
    .map({
        "true": True,
        "false": False,
        "": False,
        "nan": False
    })
    .fillna(False)
)

# Normalize first_choice: older rows (scraped before this column existed)
# simply don't have it -- blank means "not captured," never "no first
# choice," and is always treated that way downstream.
if "first_choice" not in df.columns:
    df["first_choice"] = ""
df["first_choice"] = df["first_choice"].fillna("")

# Parse dates and sort chronologically
df["posted_dt"] = pd.to_datetime(df["posted"], errors="coerce")

bad_dates = df["posted_dt"].isna().sum()
if bad_dates > 0:
    print(f"WARNING: {bad_dates} rows have invalid posted dates and will be kept but sorted last.")

df = df.sort_values("posted_dt", na_position="last").reset_index(drop=True)

latest_date = df["posted_dt"].max()

# Remove helper column before saving
df = df.drop(columns=["posted_dt"])

# Validate every pool this scrape run touched before writing anything.
# On failure, master_history_raw.csv is left completely untouched -- the
# scheduled run will simply retry the scrape next cycle rather than risk
# writing a corrupted row.
touched_pools = find_touched_pools(update)
problems = validate_pools(df, touched_pools)
if problems:
    print("")
    print("⚠ VALIDATION FAILED -- refusing to write master_history_raw.csv:")
    for p in problems:
        print(f"  - {p}")
    print("")
    print("Master history was NOT updated. Will retry on the next scheduled run.")
    sys.exit(1)

# Save rebuilt master history
df.to_csv(MASTER_FILE, index=False)

print("")
print("Master history rebuilt successfully.")
print(f"Final row count: {len(df)}")
print(f"Newest date: {latest_date}")

merge_pool_standings()
