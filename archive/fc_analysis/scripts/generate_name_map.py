"""
Name Map Generator

Builds a lookup from DEN's abbreviated player names ("E Kramer", as shown
on bracket/matches pages and used throughout fc_tracking.csv) to full names
("Eric Kramer", as recorded in master_history_raw.csv), so the FC
Leaderboard viewer can display full names while still matching/filtering
on the abbreviated form underneath.

If two different full names normalize to the same abbreviation (e.g. two
different "S Kramer"s), that abbreviation is marked ambiguous and excluded
from the map -- the viewer will just show the abbreviated form for those,
rather than risk showing the wrong person's full name.

USAGE:
    python3 generate_name_map.py

Reads:
    ../../data/master_history_raw.csv

Writes:
    ../output/name_map.csv   (columns: abbreviated, full_name)
"""

import csv
import re
from collections import defaultdict
from pathlib import Path

MASTER_HISTORY_PATH = Path("../../data/master_history_raw.csv")
OUTPUT_PATH = Path("../output/name_map.csv")


def normalize_name(name):
    """'Eric Kramer' -> 'E Kramer'. Already-abbreviated names pass through unchanged."""
    name = re.sub(r"\s+", " ", name.strip())
    if not name:
        return ""
    parts = name.split(" ")
    if len(parts) == 1:
        return parts[0]
    first, last = parts[0], parts[-1]
    if len(first) == 1:
        return f"{first} {last}"
    return f"{first[0]} {last}"


def main():
    if not MASTER_HISTORY_PATH.exists():
        print(f"Could not find {MASTER_HISTORY_PATH.resolve()}")
        return

    full_names_by_abbrev = defaultdict(set)

    with open(MASTER_HISTORY_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            for team_field in ("winning_team", "losing_team"):
                names = (row.get(team_field) or "").split("/")
                for name in names:
                    name = name.strip()
                    if not name:
                        continue
                    abbrev = normalize_name(name)
                    if abbrev:
                        full_names_by_abbrev[abbrev].add(name)

    OUTPUT_PATH.parent.mkdir(exist_ok=True)

    written = 0
    ambiguous = 0

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["abbreviated", "full_name"])

        for abbrev, full_names in sorted(full_names_by_abbrev.items()):
            if len(full_names) == 1:
                writer.writerow([abbrev, next(iter(full_names))])
                written += 1
            else:
                # Ambiguous -- multiple different full names map to the same
                # abbreviation. Skip it; the viewer will fall back to showing
                # the abbreviated form for these rather than guess wrong.
                ambiguous += 1
                print(f"  Ambiguous: '{abbrev}' could be {sorted(full_names)} -- skipped.")

    print(f"\nWrote {written} name mappings to {OUTPUT_PATH.resolve()}")
    if ambiguous:
        print(f"{ambiguous} abbreviation(s) were ambiguous and skipped (shown above).")


if __name__ == "__main__":
    main()
