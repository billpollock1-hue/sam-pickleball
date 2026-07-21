import json
import os
import re
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from playwright.sync_api import sync_playwright

import generate_assignments_viewer

RATINGS_URL = "https://app.pickleballden.com/ShootoutViewInternal"
SIGNUP_URL = "https://app.pickleballden.com/clubSignUpSheetView"

STARTING_COURT = 3
PLAYERS_PER_COURT = 4

# Repo root is the parent of this file's directory (assignments/).
# When PB_RUNTIME is set (headless refresh under the launchd monitor, which
# cannot access ~/Documents), all paths resolve inside that runtime dir and
# model files are the copies synced there by run_all.sh.
ASSIGNMENTS_DIR = Path(__file__).resolve().parent
_RUNTIME = os.environ.get("PB_RUNTIME")

if _RUNTIME:
    _BASE = Path(_RUNTIME)
    MODEL_DIR = _BASE
    MODEL_OUTPUT = _BASE / "pickleball_model_latest.xlsx"
    MODEL_INPUT = _BASE / "master_history_raw.csv"
    MODEL_SCRIPT = _BASE / "engine-not-available"  # ensure_model_current is never called in auto mode
    OUT_DIR = _BASE / "output"
    SESSION_FILE = str(_BASE / "den_session.json")
else:
    MODEL_DIR = ASSIGNMENTS_DIR.parent
    MODEL_OUTPUT = MODEL_DIR / "output" / "pickleball_model_latest.xlsx"
    MODEL_INPUT = MODEL_DIR / "data" / "master_history_raw.csv"
    MODEL_SCRIPT = MODEL_DIR / "engine" / "pickleball_engine_v2.py"
    OUT_DIR = ASSIGNMENTS_DIR / "output"
    SESSION_FILE = str(ASSIGNMENTS_DIR / "den_session.json")

OUT_DIR.mkdir(exist_ok=True, parents=True)

HISTORY_DIR = OUT_DIR / "assignments_history"

# Rolling snapshot of current DEN membership (added 2026-07-21): DEN's ratings
# page only lists current members, so presence of a player's name in this file
# is itself the membership signal -- no separate boolean needed. Written each
# run by refresh_assignments.py's fetch_den_ratings() (unconditional, not
# gated behind DEBUG_MODE like the older debug/ratings_latest.csv dump).
MEMBERSHIP_FILE = MODEL_INPUT.parent / "den_current_members.csv"
HISTORY_DIR.mkdir(exist_ok=True, parents=True)
DEBUG_MODE = False


def cleanup_output_folder():
    OUT_DIR.mkdir(exist_ok=True)

    clutter_patterns = [
        "signup_page_*.txt",
        "ratings_page_*.txt",
        "signup_page_retry_*.txt",
        "ratings_page_retry_*.txt",
        "signups.csv",
        "ratings.csv",
        "waitlist.csv",
        "court_assignments.csv",
        "*_6AM_Court_Assignments.csv",
    ]

    for pattern in clutter_patterns:
        for file in OUT_DIR.glob(pattern):
            try:
                file.unlink()
            except OSError:
                pass


def clean_name(name):
    return re.sub(r"\s+", " ", str(name).strip())


def next_weekday_date():
    """
    Date-selection rule:
    - If Phoenix time is before 5:55 AM and today is Monday-Friday, use today's sheet.
    - Otherwise use the next weekday.
    """
    phoenix_now = datetime.now(ZoneInfo("America/Phoenix"))
    today = phoenix_now.date()

    if (
        today.weekday() < 5
        and (
            phoenix_now.hour < 5
            or (phoenix_now.hour == 5 and phoenix_now.minute < 55)
        )
    ):
        return today

    d = today + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)

    return d


def format_den_date(d):
    return f"{d.month}/{d.day}/{d.year}"

def format_display_date(d):
    try:
        return d.strftime("%A, %B %-d, %Y")
    except ValueError:
        return d.strftime("%A, %B %d, %Y")



def clean_percent(value):
    text = str(value).strip().replace("%", "")
    try:
        return float(text)
    except ValueError:
        return None


def save_page_text(page, filename):
    text = page.locator("body").inner_text()

    if DEBUG_MODE:
        debug_dir = OUT_DIR / "debug"
        debug_dir.mkdir(exist_ok=True)

        if filename.startswith("signup_page"):
            path = debug_dir / "signup_page_latest.txt"
        elif filename.startswith("ratings_page"):
            path = debug_dir / "ratings_page_latest.txt"
        else:
            path = debug_dir / filename

        path.write_text(text, encoding="utf-8")

    return text


def extract_signup_names_from_text(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    names = []

    for i, line in enumerate(lines):
        m = re.match(r"^(\d+)\)\s+Member$", line)
        if not m:
            continue

        if i + 1 < len(lines):
            possible_name = clean_name(lines[i + 1])
            if possible_name:
                names.append(possible_name)

    seen = set()
    ordered = []

    for name in names:
        key = name.lower()
        if key not in seen:
            seen.add(key)
            ordered.append(name)

    return pd.DataFrame({
        "SignupOrder": range(1, len(ordered) + 1),
        "Player": ordered,
    })



def automate_signup_search(page):
    target_date = next_weekday_date()
    target_text = format_den_date(target_date)

    print(f"\nSearching signup sheet for: {target_text}")

    try:
        page.wait_for_selector("input", timeout=8000)
        inputs = page.locator("input")
        count = inputs.count()

        if count < 2:
            raise RuntimeError("Could not find both date fields.")

        for i in range(2):
            field = inputs.nth(i)
            field.click()
            field.press("Meta+A")
            field.fill(target_text)
            field.press("Tab")

        page.get_by_text("SEARCH", exact=True).click()
        page.wait_for_timeout(2500)

    except Exception as e:
        print(f"Automatic date/search step failed: {e}")
        input("Manually set the date, click SEARCH, then press Return here... ")

    try:
        body_text = page.locator("body").inner_text()
        if "Hide Players" in body_text and re.search(r"\d+\)\s+Member", body_text):
            print("View Players already appears to be open.")
            return

        page.get_by_text("View Players", exact=True).click()
        page.wait_for_timeout(1200)

    except Exception as e:
        print(f"Could not automatically open View Players: {e}")
        input("Open View Players manually, then press Return here... ")


def extract_play_date(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # Best source: the event date immediately above the expanded player list.
    first_player_index = None
    for i, line in enumerate(lines):
        if re.match(r"^1\)\s+Member$", line):
            first_player_index = i
            break

    if first_player_index is not None:
        for j in range(first_player_index - 1, -1, -1):
            if "6:00AM" in lines[j]:
                display_line = lines[j]
                m = re.search(r"([A-Z][a-z]{2},\s+[A-Z][a-z]{2}\s+\d{1,2}),\s+6:00AM", display_line)
                if m:
                    display = m.group(1)
                    try:
                        year = datetime.now(ZoneInfo("America/Phoenix")).year
                        dt = datetime.strptime(f"{display} {year}", "%a, %b %d %Y")
                        return format_display_date(dt.date()), dt.strftime("%Y-%m-%d")
                    except ValueError:
                        break

    # Fallback: first 6:00AM line found anywhere.
    m = re.search(r"([A-Z][a-z]{2},\s+[A-Z][a-z]{2}\s+\d{1,2}),\s+6:00AM", text)
    if m:
        display = m.group(1)
        try:
            year = datetime.now(ZoneInfo("America/Phoenix")).year
            dt = datetime.strptime(f"{display} {year}", "%a, %b %d %Y")
            return format_display_date(dt.date()), dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    d = target_play_date()
    return format_display_date(d), d.strftime("%Y-%m-%d")


def extract_ratings_from_text(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    rows = []

    for i in range(len(lines) - 4):
        player = clean_name(lines[i])
        rounds = lines[i + 1]
        step = lines[i + 2]
        last_played = lines[i + 3]
        pct = lines[i + 4]

        if "%" not in pct:
            continue
        if not re.match(r"^\d+$", str(rounds)):
            continue
        if not re.match(r"^\d+$", str(step)):
            continue

        pct_num = clean_percent(pct)
        if pct_num is None:
            continue

        if player.lower() in {
            "player",
            "home",
            "friends",
            "timeline",
            "search",
            "account",
        }:
            continue

        rows.append({
            "Player": player,
            "Rounds": int(rounds),
            "Step": int(step),
            "Last Played": last_played,
            "Percent": pct_num,
        })

    df = pd.DataFrame(rows)

    if not df.empty:
        df["Player"] = df["Player"].apply(clean_name)
        df = df.drop_duplicates(subset=["Player"], keep="first")

    return df


def assign_courts(signups, ratings):
    total_signed_up = len(signups)
    eligible_count = (total_signed_up // PLAYERS_PER_COURT) * PLAYERS_PER_COURT

    # Signup order controls who is eligible for courts.
    # Any excess players go to the waitlist based only on signup order.
    eligible = signups.iloc[:eligible_count].copy()
    waitlist = signups.iloc[eligible_count:].copy()

    # Players seated at a real court are no longer "waitlisted" even if the
    # signup sheet still tags their name that way — strip it so the ratings
    # merge matches and the displayed name reflects their actual seat.
    eligible["Player"] = eligible["Player"].astype(str).str.replace(
        "(Wait List)", "", regex=False
    ).str.strip()

    merged = eligible.merge(
        ratings[["Player", "Step", "Percent"]],
        on="Player",
        how="left",
    )

    # Special DEN placeholder player:
    # Treat this as unrated even if it happens to match something in ratings.
    # It should go to the bottom of the eligible court-ranking order.
    merged["_ForceBottom"] = (
        merged["Player"].str.strip().str.lower().eq("den new player tryout")
    )

    merged["_MissingRating"] = (
        merged["Step"].isna()
        | merged["Percent"].isna()
        | merged["_ForceBottom"]
    )

    ranked = merged.sort_values(
        by=["_MissingRating", "Step", "Percent", "SignupOrder"],
        ascending=[True, True, False, True],
    ).reset_index(drop=True)

    # Blank out Step/% for DEN New Player Tryout so the PDF/CSV do not show
    # a misleading rating.
    ranked.loc[ranked["_ForceBottom"], ["Step", "Percent"]] = pd.NA

    ranked["Court"] = STARTING_COURT + (ranked.index // PLAYERS_PER_COURT)
    ranked["CourtPosition"] = (ranked.index % PLAYERS_PER_COURT) + 1

    ranked = ranked.drop(columns=["_MissingRating", "_ForceBottom"])

    if not waitlist.empty:
        waitlist = waitlist.copy()
        waitlist["WaitlistPosition"] = range(1, len(waitlist) + 1)

        waitlist["PlayerDisplay"] = waitlist["Player"].astype(str).str.replace(
            "(Wait List)", "", regex=False
        ).str.strip()

        ratings_for_waitlist = ratings[["Player", "Step", "Percent"]].copy()
        ratings_for_waitlist["PlayerDisplay"] = ratings_for_waitlist["Player"].astype(str).str.strip()

        waitlist = waitlist.merge(
            ratings_for_waitlist[["PlayerDisplay", "Step", "Percent"]],
            on="PlayerDisplay",
            how="left",
        )

    return ranked, waitlist


def shorten_name(name, max_len=22):
    name = clean_name(name)
    return name if len(name) <= max_len else name[: max_len - 1] + "…"


def _courts_to_json(assignments, waitlist, is_rating):
    """Convert an assignments/waitlist DataFrame pair into JSON-friendly lists.

    Guarded for the empty-DEN-ratings fallback case: when the DEN session is
    expired, refresh_assignments.py passes an empty, columnless DataFrame for
    `assignments` here. Without this guard, `.groupby("Court")` raises
    KeyError: 'Court' since the column doesn't exist on an empty DataFrame
    with no columns at all.
    """
    courts = []
    if not assignments.empty and "Court" in assignments.columns:
        for court, group in assignments.groupby("Court"):
            players = []
            for _, r in group.sort_values("CourtPosition").iterrows():
                entry = {
                    "pos": int(r["CourtPosition"]),
                    "su": int(r["SignupOrder"]),
                    "name": shorten_name(r["Player"], 22),
                }
                if is_rating:
                    entry["rating"] = None if pd.isna(r.get("Rating")) else int(round(r["Rating"]))
                else:
                    entry["step"] = None if pd.isna(r["Step"]) else int(r["Step"])
                    entry["pct"] = None if pd.isna(r["Percent"]) else round(float(r["Percent"]), 1)
                players.append(entry)
            courts.append({"court": int(court), "players": players})

    wl = []
    if not waitlist.empty:
        for _, r in waitlist.iterrows():
            entry = {
                "pos": int(r["WaitlistPosition"]),
                "su": int(r["SignupOrder"]),
                "name": shorten_name(str(r["Player"]).replace("(Wait List)", "").strip(), 26),
            }
            if is_rating:
                entry["rating"] = None if pd.isna(r.get("Rating")) else int(round(r["Rating"]))
            else:
                entry["step"] = None if pd.isna(r["Step"]) else int(r["Step"])
                entry["pct"] = None if pd.isna(r["Percent"]) else round(float(r["Percent"]), 1)
            wl.append(entry)

    return {"courts": courts, "waitlist": wl}


def _comparison_to_json(den_assignments, rating_assignments):
    """Guarded the same way as _courts_to_json above: when DEN ratings are
    unavailable, `den_assignments` is an empty, columnless DataFrame, and
    `.iterrows()` over `r["Player"]`/`r["Court"]` would raise a KeyError.
    In that case there's nothing to compare against, so return an empty
    comparison rather than crashing the whole refresh.
    """
    if (
        den_assignments.empty
        or "Player" not in den_assignments.columns
        or "Court" not in den_assignments.columns
    ):
        return {"rows": [], "moved": 0, "total": 0}

    den_map = {r["Player"]: int(r["Court"]) for _, r in den_assignments.iterrows()}
    rat_map = {r["Player"]: int(r["Court"]) for _, r in rating_assignments.iterrows()}

    rows = []
    for _, r in rating_assignments.sort_values(["Court", "CourtPosition"]).iterrows():
        player = r["Player"]
        den_court = den_map.get(player)
        rat_court = rat_map.get(player)
        if den_court is None or rat_court is None:
            continue
        rows.append({
            "name": shorten_name(player, 24),
            "den_court": den_court,
            "rating_court": rat_court,
            "diff": den_court - rat_court,
        })

    moved = sum(1 for p in rat_map if p in den_map and den_map[p] != rat_map[p])
    total = sum(1 for p in rat_map if p in den_map)

    return {"rows": rows, "moved": moved, "total": total}


def _last_signup_change(play_date_file):
    """Return the most recent signup change timestamp for a date, or None."""
    log_file = Path(PBMONITOR_LOGS) / f"{play_date_file}_signup_log.csv"
    if not log_file.exists():
        return None
    try:
        import csv
        last_ts = None
        with open(log_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts = row.get("timestamp_mt", "").strip().strip('"')
                if ts and not ts.startswith("#"):
                    last_ts = ts
        return last_ts
    except Exception:
        return None

PBMONITOR_LOGS = Path.home() / "Library" / "Application Support" / "PBMonitor" / "logs"

def save_assignments_snapshot(assignments, waitlist, play_date_file, play_date_display,
                               total_signups, rating_assignments=None, rating_waitlist=None,
                               ratings_through=None, den_current=True):
    """Write this session's court assignments to a JSON snapshot for the HTML viewer."""
    generated = datetime.now(ZoneInfo("America/Phoenix")).strftime("%m/%d/%Y %I:%M %p MST")

    snapshot = {
        "date_display": play_date_display,
        "generated": generated,
        "total_signups": total_signups,
        "ratings_through": ratings_through.strftime("%-m/%-d/%y") if ratings_through else None,
        "den_current": den_current,
        "last_signup_change": _last_signup_change(play_date_file),
        "den": _courts_to_json(assignments, waitlist, is_rating=False),
    }

    if rating_assignments is not None:
        snapshot["rating"] = _courts_to_json(
            rating_assignments,
            rating_waitlist if rating_waitlist is not None else waitlist,
            is_rating=True,
        )
        snapshot["comparison"] = _comparison_to_json(assignments, rating_assignments)

    out_path = HISTORY_DIR / f"{play_date_file}.json"
    out_path.write_text(json.dumps(snapshot, indent=2))
    print(f"✓ Saved assignments snapshot: {out_path}")
    return out_path


def print_assignments(assignments, waitlist):
    print("\nCOURT ASSIGNMENTS")
    print("=================")

    for court, group in assignments.groupby("Court"):
        print(f"\nCourt {court}")
        print("-" * 20)

        for _, row in group.iterrows():
            if not pd.isna(row["Step"]) and not pd.isna(row["Percent"]):
                rating = f"  Step {int(row['Step'])}, {row['Percent']:.2f}%"
            else:
                rating = "  MISSING RATING"

            print(
                f"{int(row['CourtPosition'])}. {row['Player']} "
                f"(Signup {int(row['SignupOrder'])}){rating}"
            )

    print("\nWAIT LIST")
    print("=========")

    if waitlist.empty:
        print("None")
    else:
        for _, row in waitlist.iterrows():
            print(
                f"{int(row['WaitlistPosition'])}. {row['Player']} "
                f"(Signup {int(row['SignupOrder'])})"
            )


def main():
    cleanup_output_folder()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    ratings_through = ensure_model_current()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        if Path(SESSION_FILE).exists():
            context = browser.new_context(storage_state=SESSION_FILE)
        else:
            context = browser.new_context()

        page = context.new_page()

        print("\nOpening Pickleball Den signup page...")
        page.goto(SIGNUP_URL, wait_until="domcontentloaded")

        print("\nManual signup sheet step:")
        print("In the browser:")
        print("1. Log in if needed.")
        print("2. Navigate to Sign-Up Sheet View if needed.")
        print("3. Select the correct 6:00 AM sheet.")
        print("4. Click SEARCH if needed.")
        print("5. Expand View Players so the names are visible.")
        input("Then press Return here to scrape the signup list... ")

        signup_text = save_page_text(page, f"signup_page_{timestamp}.txt")
        play_date_display, play_date_file = extract_play_date(signup_text)

        signups = extract_signup_names_from_text(signup_text)
        if DEBUG_MODE:
            signups.to_csv(OUT_DIR / "debug" / "signups_latest.csv", index=False)

        print(f"\nFound {len(signups)} signup players.")

        if signups.empty:
            print("No signup players were detected.")
            print("If View Players did not open, open it manually and rerun.")
            browser.close()
            return

        print("\nOpening ratings page...")
        page.goto(RATINGS_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        ratings_text = save_page_text(page, f"ratings_page_{timestamp}.txt")
        ratings = extract_ratings_from_text(ratings_text)
        if DEBUG_MODE:
            ratings.to_csv(OUT_DIR / "debug" / "ratings_latest.csv", index=False)

        print(f"\nFound {len(ratings)} ratings rows.")

        if ratings.empty:
            input("Ratings were not detected. Make sure the ratings table is visible, then press Return... ")
            ratings_text = save_page_text(page, f"ratings_page_retry_{timestamp}.txt")
            ratings = extract_ratings_from_text(ratings_text)
            if DEBUG_MODE:
                ratings.to_csv(OUT_DIR / "debug" / "ratings_latest.csv", index=False)

        if ratings.empty:
            print("No ratings rows were detected.")
            browser.close()
            return

        context.storage_state(path=SESSION_FILE)

        assignments, waitlist = assign_courts(signups, ratings)

        player_ratings = load_player_ratings()
        rating_assignments = None
        rating_waitlist = None
        if not player_ratings.empty:
            rating_assignments, rating_waitlist = assign_courts_by_rating(signups, player_ratings)
            print(f"\nPlayer ratings loaded for {len(player_ratings)} players.")
        else:
            print("\nNo player ratings available – viewer will only contain DEN assignments.")

        if DEBUG_MODE:
            csv_assignments = assignments[[
                "Court",
                "CourtPosition",
                "SignupOrder",
                "Player",
                "Step",
                "Percent",
            ]]
            csv_assignments.to_csv(OUT_DIR / "debug" / "court_assignments_latest.csv", index=False)
            waitlist.to_csv(OUT_DIR / "debug" / "waitlist_latest.csv", index=False)

        save_assignments_snapshot(
            assignments, waitlist, play_date_file, play_date_display, len(signups),
            rating_assignments=rating_assignments, rating_waitlist=rating_waitlist,
            ratings_through=ratings_through,
        )

        print_assignments(assignments, waitlist)

        if rating_assignments is not None:
            print("\n\nRATING MODEL COURT ASSIGNMENTS")
            print("=============================")
            for court, group in rating_assignments.groupby("Court"):
                print(f"\nCourt {court}")
                print("-" * 20)
                for _, row in group.iterrows():
                    rat = "" if pd.isna(row["Rating"]) else f"  Rating {int(round(row['Rating']))}"
                    print(f"{int(row['CourtPosition'])}. {row['Player']} "
                                  f"(Signup {int(row['SignupOrder'])}){rat}")

        if DEBUG_MODE:
            print("\nFiles created:")
            print(f"- {OUT_DIR / 'debug' / 'court_assignments_latest.csv'}")
            print(f"- {OUT_DIR / 'debug' / 'waitlist_latest.csv'}")
            print(f"- {OUT_DIR / 'debug' / 'ratings_latest.csv'}")
            print(f"- {OUT_DIR / 'debug' / 'signups_latest.csv'}")

        browser.close()

    viewer_path = generate_assignments_viewer.generate_viewer()
    if viewer_path:
        subprocess.run(["open", str(viewer_path)], check=False)


EARLIEST_RESULTS_HOUR_MT = 8
EARLIEST_RESULTS_MINUTE_MT = 15  # 6-8 AM games must finish before results can post


def ensure_model_current():
    if not MODEL_INPUT.exists() or not MODEL_SCRIPT.exists():
        print(f"\nModel input or script not found – skipping freshness check.")
        return

    # Step 1: Check if today's shootout results are in the CSV
    raw = pd.read_csv(MODEL_INPUT)
    raw.columns = [c.strip() for c in raw.columns]
    raw_latest = pd.to_datetime(raw["posted"], errors="coerce").max().date()

    now_mt = datetime.now(ZoneInfo("America/Phoenix"))
    today = now_mt.date()

    too_early = (now_mt.hour, now_mt.minute) < (EARLIEST_RESULTS_HOUR_MT, EARLIEST_RESULTS_MINUTE_MT)
    if today > raw_latest and too_early:
        print(f"\nToday is {today}; latest data in CSV is {raw_latest}, but it's only "
              f"{now_mt.strftime('%I:%M %p')} MST — too early for results to be posted. Skipping scrape.")
    elif today > raw_latest:
        print(f"\nToday is {today}; latest data in CSV is {raw_latest}. Scraping today's results...")
        scrape_script = MODEL_DIR / "scraper" / "scrape.js"
        today_csv = MODEL_DIR / "output" / "today_results.csv"
        today_str = today.strftime("%m%d%y")

        if scrape_script.exists():
            # scrape.js prompts for manual login/navigation via the terminal
            # (readline), so stdin/stdout must stay connected to this
            # terminal — capturing output would hide those prompts and the
            # process would hang until it times out with no way to respond.
            try:
                result = subprocess.run(
                    ["node", str(scrape_script), "--start", today_str, "--end", today_str,
                     "--output", str(today_csv)],
                    cwd=str(MODEL_DIR),
                )
                if result.returncode == 0 and today_csv.exists():
                    scraped = pd.read_csv(today_csv)
                    # Drop duplicate header rows safely
                    first_col = scraped.columns[0]
                    scraped = scraped[scraped[first_col] != first_col]
                    scraped = scraped.reset_index(drop=True)
                    if len(scraped) > 0:
                        scraped.to_csv(MODEL_INPUT, mode="a", header=False, index=False)
                        raw_latest = today
                        print(f"✓ Appended {len(scraped)} rows from today's scrape to master CSV.")
                    else:
                        print(f"⚠ Scrape ran but returned no rows for {today_str}. Results may not be posted yet.")
                else:
                    print(f"⚠ Scrape exited with code {result.returncode}. Results may not be posted yet.")
            except Exception as e:
                print(f"⚠ Scraping error: {e}")
        else:
            print(f"⚠ Scrape script not found: {scrape_script}")
    else:
        print(f"\nCSV is up to date through {raw_latest}.")

    # Step 2: Check if model needs regeneration
    if MODEL_OUTPUT.exists():
        lb = pd.read_excel(MODEL_OUTPUT, sheet_name="Leaderboard")
        model_latest = pd.to_datetime(lb["Last Played"]).max().date()
    else:
        model_latest = None

    if model_latest and model_latest >= raw_latest:
        print(f"Model is current (latest data: {raw_latest}, model: {model_latest}).")
        return raw_latest

    print(f"Model is stale (latest data: {raw_latest}, model: {model_latest}). Re-running model...")
    result = subprocess.run(
        ["python3", str(MODEL_SCRIPT),
         "--input", str(MODEL_INPUT),
         "--output", str(MODEL_OUTPUT)],
        cwd=str(MODEL_DIR),
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"Model re-run failed:\n{result.stderr[-500:]}")
    else:
        print("Model re-run complete.")

    return raw_latest


def load_player_ratings():
    if not MODEL_OUTPUT.exists():
        print(f"\nModel output not found: {MODEL_OUTPUT}")
        return pd.DataFrame()

    try:
        lb = pd.read_excel(MODEL_OUTPUT, sheet_name="Leaderboard")
        lb_ratings = lb[["Player", "Player Rating"]].rename(
            columns={"Player Rating": "Rating"}
        )
        lb_players = set(lb_ratings["Player"])

        gl = pd.read_excel(MODEL_OUTPUT, sheet_name="Player_Game_Log")
        gl = gl[gl["include_in_ratings"] == "Yes"].sort_values(["posted_dt", "match_id"])

        as_of = pd.to_datetime(gl["posted_dt"]).max().normalize()

        fallback_rows = []
        for p, sub in gl.groupby("player"):
            if p in lb_players:
                continue

            recent = sub.tail(60)
            g = len(recent)
            raw_rating = float(recent["player_post_rating"].iloc[-1])

            last_played = pd.Timestamp(recent["posted"].iloc[-1]).date()
            days_since = (as_of.date() - last_played).days

            sample_conf = 1.0 if g >= 60 else g / (g + 10)

            if days_since <= 90:
                fresh_conf = 1.0
            else:
                excess = min(days_since - 90, 365)
                fresh_conf = max(1.0 - excess * 0.15 / 365, 0.85)

            rating_conf = sample_conf * fresh_conf
            player_rating = 1000 + ((raw_rating - 1000) * rating_conf * 0.60)

            fallback_rows.append({"Player": p, "Rating": int(round(player_rating))})

        if fallback_rows:
            fallback = pd.DataFrame(fallback_rows)
            combined = pd.concat([lb_ratings, fallback], ignore_index=True)
        else:
            combined = lb_ratings

        on_lb = len(lb_ratings)
        off_lb = len(fallback_rows)
        print(f"\n  {on_lb} players from Leaderboard, {off_lb} with credibility-adjusted ratings.")

        return combined

    except Exception as e:
        print(f"\nFailed to load player ratings: {e}")
        return pd.DataFrame()


def assign_courts_by_rating(signups, player_ratings):
    total_signed_up = len(signups)
    eligible_count = (total_signed_up // PLAYERS_PER_COURT) * PLAYERS_PER_COURT

    eligible = signups.iloc[:eligible_count].copy()
    waitlist = signups.iloc[eligible_count:].copy()

    # Players seated at a real court are no longer "waitlisted" even if the
    # signup sheet still tags their name that way — strip it so the ratings
    # merge matches and the displayed name reflects their actual seat.
    eligible["Player"] = eligible["Player"].astype(str).str.replace(
        "(Wait List)", "", regex=False
    ).str.strip()

    merged = eligible.merge(player_ratings, on="Player", how="left")

    merged["_ForceBottom"] = (
        merged["Player"].str.strip().str.lower().eq("den new player tryout")
    )
    merged["_MissingRating"] = merged["Rating"].isna() | merged["_ForceBottom"]

    ranked = merged.sort_values(
        by=["_MissingRating", "Rating", "SignupOrder"],
        ascending=[True, False, True],
    ).reset_index(drop=True)

    ranked.loc[ranked["_ForceBottom"], "Rating"] = pd.NA

    ranked["Court"] = STARTING_COURT + (ranked.index // PLAYERS_PER_COURT)
    ranked["CourtPosition"] = (ranked.index % PLAYERS_PER_COURT) + 1

    ranked = ranked.drop(columns=["_MissingRating", "_ForceBottom"])

    if not waitlist.empty:
        waitlist = waitlist.copy()
        waitlist["WaitlistPosition"] = range(1, len(waitlist) + 1)
        waitlist["PlayerDisplay"] = waitlist["Player"].astype(str).str.replace(
            "(Wait List)", "", regex=False
        ).str.strip()
        ratings_wl = player_ratings.copy()
        ratings_wl["PlayerDisplay"] = ratings_wl["Player"].str.strip()
        waitlist = waitlist.merge(
            ratings_wl[["PlayerDisplay", "Rating"]],
            on="PlayerDisplay",
            how="left",
        )

    return ranked, waitlist


if __name__ == "__main__":
    main()
