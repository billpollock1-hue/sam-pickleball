"""
Per-Game Name Resolution

Resolves DEN's abbreviated player names ("C Smith") to full names ("Camie
Smith" or "Colin Smith") on a PER-GAME basis, rather than a single global
lookup table. This matters because a flat abbreviation -> full name map
can't distinguish two different real people who share the same first
initial and last name -- if both a "Camie Smith" and a "Colin Smith" exist
in your history, every "C Smith" row in fc_tracking.csv is currently being
silently treated as the same person in the leaderboard, win rate, and
streak calculations.

This resolves the ambiguity using the same technique fc_win_rate.py already
uses to match games between the two files: for a given date, the exact set
of 4 players in a round-robin group is (almost always) unique, so knowing
who the OTHER 3 players were in a specific game is usually enough to tell
Camie's games apart from Colin's games, even though both look like "C
Smith" in isolation.

USAGE:
    python3 resolve_names.py

Reads:
    ../../data/master_history_raw.csv
    ../output/fc_tracking.csv
    ../output/fc_win_rate_results.csv   (if present)

Writes:
    ../output/fc_tracking_resolved.csv
    ../output/fc_win_rate_results_resolved.csv   (if input was present)

Prints a diagnostic report, including any abbreviation that resolves to
more than one distinct full name (a genuine same-initials collision) so
you can see it's being separated correctly rather than guessed at.
"""

import csv
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

MASTER_HISTORY_PATH = Path("../../data/master_history_raw.csv")
FC_TRACKING_PATH = Path("../output/fc_tracking.csv")
FC_WIN_RATE_PATH = Path("../output/fc_win_rate_results.csv")
FC_TRACKING_OUT = Path("../output/fc_tracking_resolved.csv")
FC_WIN_RATE_OUT = Path("../output/fc_win_rate_results_resolved.csv")


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


def parse_master_history(path):
    """Returns list of games: {date, dt, players: {abbrev: full_name for the 4 players}}"""
    games = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (row.get("exclude_match") or "").strip().lower() == "true":
                continue

            posted = (row.get("posted") or "").strip()
            try:
                dt = datetime.strptime(posted, "%b %d, %Y, %I:%M %p")
            except ValueError:
                try:
                    dt = datetime.strptime(posted, "%B %d, %Y, %I:%M %p")
                except ValueError:
                    continue

            all_names = []
            for field in ("winning_team", "losing_team"):
                names = (row.get(field) or "").split("/")
                all_names.extend(n.strip() for n in names if n.strip())

            if len(all_names) != 4:
                continue

            players = {}
            ok = True
            for full_name in all_names:
                abbrev = normalize_name(full_name)
                if not abbrev:
                    ok = False
                    break
                players[abbrev] = full_name
            if not ok or len(players) != 4:
                continue

            games.append(
                {
                    "date": dt.strftime("%Y-%m-%d"),
                    "dt": dt,
                    "players": players,  # abbrev -> full_name, for this specific game
                    "player_set": frozenset(players.keys()),
                }
            )

    games.sort(key=lambda g: g["dt"])
    return games


def group_by_date_playerset(games, key_fn):
    groups = defaultdict(list)
    for g in games:
        groups[(g["date"], key_fn(g))].append(g)
    return groups


def resolve_fc_tracking(fc_rows, history_groups):
    """Returns (resolved_rows, stats) where resolved_rows has full names
    substituted in place of abbreviated ones wherever a match was found."""

    # Group fc_tracking rows the same way, ordered by game_number within each group
    fc_groups = defaultdict(list)
    for row in fc_rows:
        fc_names = [row.get("fc_player_1", "").strip(), row.get("fc_player_2", "").strip()]
        other_names = [row.get("other_player_1", "").strip(), row.get("other_player_2", "").strip()]
        player_set = frozenset(fc_names + other_names)
        fc_groups[(row.get("date", "").strip(), player_set)].append(row)

    for key in fc_groups:
        fc_groups[key].sort(key=lambda r: int(r.get("game_number", 0)) if str(r.get("game_number", "")).isdigit() else 0)

    resolved_rows = []
    matched = 0
    unmatched = 0
    resolutions_by_abbrev = defaultdict(lambda: defaultdict(int))  # abbrev -> {full_name: count}

    for key, fc_list in fc_groups.items():
        hist_list = history_groups.get(key)

        for i, row in enumerate(fc_list):
            new_row = dict(row)

            if hist_list and i < len(hist_list):
                players_map = hist_list[i]["players"]  # abbrev -> full_name for this exact game
                matched += 1
                for field in ("fc_player_1", "fc_player_2", "other_player_1", "other_player_2"):
                    abbrev = row.get(field, "").strip()
                    full = players_map.get(abbrev)
                    if full:
                        new_row[field] = full
                        resolutions_by_abbrev[abbrev][full] += 1
                    # else: leave the abbreviated form as-is (no resolution found for this player)
            else:
                unmatched += 1
                # leave row entirely as abbreviated -- no matching game found

            resolved_rows.append(new_row)

    return resolved_rows, matched, unmatched, resolutions_by_abbrev


def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    if not MASTER_HISTORY_PATH.exists():
        print(f"Could not find {MASTER_HISTORY_PATH.resolve()}")
        return
    if not FC_TRACKING_PATH.exists():
        print(f"Could not find {FC_TRACKING_PATH.resolve()}")
        return

    print("Loading master_history_raw.csv...")
    history_games = parse_master_history(MASTER_HISTORY_PATH)
    print(f"  {len(history_games)} usable games loaded.")

    history_groups = group_by_date_playerset(history_games, lambda g: g["player_set"])
    for key in history_groups:
        history_groups[key].sort(key=lambda g: g["dt"])

    print("\nResolving fc_tracking.csv...")
    with open(FC_TRACKING_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fc_fieldnames = reader.fieldnames
        fc_rows = list(reader)

    resolved_rows, matched, unmatched, resolutions = resolve_fc_tracking(fc_rows, history_groups)
    write_csv(FC_TRACKING_OUT, resolved_rows, fc_fieldnames)

    print(f"  Matched {matched} of {matched + unmatched} games "
          f"({matched / (matched + unmatched) * 100:.1f}%)." if (matched + unmatched) else "  No games to match.")
    print(f"  Wrote {FC_TRACKING_OUT.resolve()}")

    # Report genuine collisions: abbreviations that resolved to more than one distinct full name
    collisions = {abbrev: names for abbrev, names in resolutions.items() if len(names) > 1}
    if collisions:
        print(f"\n{len(collisions)} abbreviation(s) resolved to multiple distinct real people "
              f"(correctly separated per-game, shown here for visibility):")
        for abbrev, names in sorted(collisions.items()):
            breakdown = ", ".join(f"{name} ({count} games)" for name, count in sorted(names.items()))
            print(f"  {abbrev} -> {breakdown}")
    else:
        print("\nNo same-initials collisions detected.")

    # Also resolve fc_win_rate_results.csv if it exists, using the same per-row field names
    if FC_WIN_RATE_PATH.exists():
        print("\nResolving fc_win_rate_results.csv...")
        with open(FC_WIN_RATE_PATH, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            wr_fieldnames = reader.fieldnames
            wr_rows = list(reader)

        wr_resolved, wr_matched, wr_unmatched, _ = resolve_fc_tracking(wr_rows, history_groups)
        write_csv(FC_WIN_RATE_OUT, wr_resolved, wr_fieldnames)
        print(f"  Matched {wr_matched} of {wr_matched + wr_unmatched} games "
              f"({wr_matched / (wr_matched + wr_unmatched) * 100:.1f}%)." if (wr_matched + wr_unmatched) else "  No games to match.")
        print(f"  Wrote {FC_WIN_RATE_OUT.resolve()}")
    else:
        print(f"\n{FC_WIN_RATE_PATH} not found -- skipping (run fc_win_rate.py first if you want this resolved too).")


if __name__ == "__main__":
    main()
