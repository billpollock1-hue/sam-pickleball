import pandas as pd

# ===============================
# LOAD DATA
# ===============================
df = pd.read_csv("data/master_history_raw.csv")

# Normalize column names
df.columns = [c.strip() for c in df.columns]

# Parse timestamp
df["posted"] = pd.to_datetime(df["posted"], errors="coerce")

# Remove bad dates
df = df.dropna(subset=["posted"])

# Filter to 2026 only
df = df[df["posted"].dt.year == 2026].copy()

# Exclude matches marked for exclusion, if column exists
if "exclude_match" in df.columns:
    df = df[df["exclude_match"].astype(str).str.lower() != "true"].copy()

# Add date column
df["date"] = df["posted"].dt.date

# Sort correctly
df = df.sort_values(by=["date", "pool", "posted"]).reset_index(drop=True)

# ===============================
# HELPERS
# ===============================
def split_team(team_name):
    """
    Converts 'Player A / Player B' into ['Player A', 'Player B'].
    """
    return [p.strip() for p in str(team_name).split("/") if p.strip()]

# ===============================
# ANALYSIS
# ===============================
pattern_results = []
total_shootouts = 0
other_details = []

for (date, pool), group in df.groupby(["date", "pool"]):

    group = group.sort_values(by="posted").reset_index(drop=True)

    # First 3 games = shootout 1, next 3 = shootout 2, etc.
    for i in range(0, len(group), 3):

        chunk = group.iloc[i:i+3]

        if len(chunk) < 3:
            continue

        total_shootouts += 1
        players = {}

        for _, row in chunk.iterrows():

            winners = split_team(row["winning_team"])
            losers = split_team(row["losing_team"])

            for p in winners + losers:
                if p not in players:
                    players[p] = {"wins": 0, "losses": 0}

            for p in winners:
                players[p]["wins"] += 1

            for p in losers:
                players[p]["losses"] += 1

        records = sorted([v["wins"] for v in players.values()], reverse=True)

        if records == [3, 1, 1, 1]:
            pattern_results.append("3-0 / 1-2 / 1-2 / 1-2")

        elif records == [2, 2, 2, 0]:
            pattern_results.append("2-1 / 2-1 / 2-1 / 0-3")

        else:
            pattern_results.append("OTHER")
            other_details.append({
                "date": date,
                "pool": pool,
                "shootout_number_within_pool": (i // 3) + 1,
                "records": records,
                "players": players
            })

# ===============================
# OUTPUT
# ===============================
summary = pd.Series(pattern_results).value_counts()

print("\n===== SHOOTOUT PATTERN COUNTS (2026) =====\n")
print(summary)

print("\n===== PERCENTAGES =====\n")
print((summary / summary.sum()).round(4))

print("\n===== TOTAL SHOOTOUTS ANALYZED =====\n")
print(total_shootouts)

if other_details:
    print("\n===== OTHER / CHECK THESE =====\n")
    for item in other_details[:20]:
        print(item)
