import pandas as pd
from pathlib import Path

MASTER_FILE = Path("data/master_history_raw.csv")
UPDATE_FILE = Path("data/latest_scrape.csv")

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

# Parse dates and sort chronologically
df["posted_dt"] = pd.to_datetime(df["posted"], errors="coerce")

bad_dates = df["posted_dt"].isna().sum()
if bad_dates > 0:
    print(f"WARNING: {bad_dates} rows have invalid posted dates and will be kept but sorted last.")

df = df.sort_values("posted_dt", na_position="last").reset_index(drop=True)

latest_date = df["posted_dt"].max()

# Remove helper column before saving
df = df.drop(columns=["posted_dt"])

# Save rebuilt master history
df.to_csv(MASTER_FILE, index=False)

print("")
print("Master history rebuilt successfully.")
print(f"Final row count: {len(df)}")
print(f"Newest date: {latest_date}")
