"""
FC (First Choice) Tracker for SAM Pickleball DEN shootouts.

Fully automatic: polls the DEN "Club Play List" page to detect when a
shootout is open, follows the same click path a person would (View Event ->
Pool Report -> View Matches per pool) to discover the current pool/bracket
URLs, then polls those pool pages every 2 minutes and logs which team is
assigned "First Choice" as soon as it's detected. Appends to a running
season CSV (output/fc_tracking.csv).

When the current shootout finishes and a NEW one is launched later in the
morning (e.g. games 4-6), the script notices the "Started" timestamp on the
Club Play List has changed and automatically re-discovers the new pool
URLs -- no manual URL entry needed.

Run this from the same folder as den_assignments.py so it can reuse the
saved login session (den_session.json). If no session exists yet, it will
prompt you to log in manually once, the same way den_assignments.py does.

USAGE:
    python3 fc_tracker.py

The script runs continuously, auto-detecting each new shootout cycle, until
MAX_RUNTIME_MINUTES elapses or you press Ctrl+C.

If auto-discovery ever fails to find an "Open" shootout or can't navigate
the site as expected, it falls back to prompting you to paste the pool
URLs manually, so tracking is never blocked.
"""

import csv
import re
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

SESSION_FILE = "../den_session.json"
LOGIN_URL = "https://app.pickleballden.com/clubSignUpSheetView"
LIST_CLUB_PLAY_URL = "https://app.pickleballden.com/listClubPlay"

OUT_DIR = Path("../output")
OUT_DIR.mkdir(exist_ok=True)
CSV_PATH = OUT_DIR / "fc_tracking.csv"

POLL_INTERVAL_SECONDS = 120
MAX_RUNTIME_MINUTES = 210  # safety cutoff (~3.5 hrs) in case the script is left running

CSV_HEADERS = [
    "date",
    "cycle_label",
    "pool_url",
    "game_number",
    "court",
    "fc_player_1",
    "fc_player_2",
    "other_player_1",
    "other_player_2",
    "detected_at",
]


def phoenix_now():
    return datetime.now(ZoneInfo("America/Phoenix"))


def ensure_csv():
    if not CSV_PATH.exists():
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADERS)


def load_logged_keys():
    """Return set of (date, pool_url, game_number) already logged, to avoid duplicates
    across script re-runs on the same day."""
    keys = set()
    if not CSV_PATH.exists():
        return keys
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            keys.add((row["date"], row["pool_url"], row["game_number"]))
    return keys


def get_pool_urls_manual():
    print("\nAuto-discovery didn't find the pool URLs. Falling back to manual entry.")
    print("Paste each bracketProgressView URL, one per line. Blank line to finish.\n")
    urls = []
    while True:
        line = input(f"Pool {len(urls) + 1} URL (or blank to finish): ").strip()
        if not line:
            break
        urls.append(line)
    return urls


def find_open_shootout(page):
    """Look at the Club Play List and return the 'Started' timestamp string
    for the currently Open shootout, or None if none is open."""
    page.goto(LIST_CLUB_PLAY_URL, wait_until="domcontentloaded")

    # This is a JS single-page app -- the grid data loads asynchronously after
    # domcontentloaded. Wait for the "Started" column header (a reliable sign
    # the grid has actually rendered) instead of guessing with a fixed delay.
    try:
        page.get_by_text("Started", exact=True).first.wait_for(timeout=10000)
    except Exception:
        pass  # fall through -- we'll still try to read whatever is there

    # Give the grid a brief moment to finish populating rows after the header appears.
    page.wait_for_timeout(1500)

    text = page.locator("body").inner_text()
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    for i, line in enumerate(lines):
        if line == "Open" and i > 0:
            started = lines[i - 1]
            return started

    # Nothing found -- dump a snippet so we can diagnose instead of guessing next time.
    print("  [debug] 'Open' not found on Club Play List. First 300 chars of page text:")
    print("  " + text[:300].replace("\n", " | "))

    return None


def discover_pool_urls(page, started_timestamp):
    """Follow the click path: Club Play List (Open row) -> View Event ->
    Pool Report -> View Matches (per pool) -> collect bracketProgressView URLs.

    Returns a list of pool URLs, or an empty list if discovery fails at any step.
    """
    try:
        page.goto(LIST_CLUB_PLAY_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1000)

        # Click the row matching the open shootout's start time to reveal actions
        page.get_by_text(started_timestamp, exact=True).first.click()
        page.wait_for_timeout(500)

        view_event = page.get_by_text("View Event", exact=True)
        if view_event.count() == 0:
            print("  ! Could not find 'View Event' link.")
            return []
        view_event.first.click()
        page.wait_for_url("**/tournamentPoolReport*", timeout=8000)
        page.wait_for_timeout(800)

        # Figure out how many pools are listed
        text = page.locator("body").inner_text()
        pool_numbers = sorted(set(int(n) for n in re.findall(r"Pool (\d+)", text)))

        if not pool_numbers:
            print("  ! No pools found on Pool Report page.")
            return []

        pool_urls = []
        for n in pool_numbers:
            page.goto(page.url, wait_until="domcontentloaded")  # fresh state each time
            page.wait_for_timeout(600)

            pool_label = page.get_by_text(f"Pool {n}", exact=True)
            if pool_label.count() == 0:
                print(f"  ! Could not find Pool {n} row.")
                continue
            pool_label.first.click()
            page.wait_for_timeout(500)

            view_matches = page.get_by_text("View Matches", exact=True)
            if view_matches.count() == 0:
                print(f"  ! Could not find 'View Matches' for Pool {n}.")
                continue
            view_matches.first.click()
            page.wait_for_url("**/bracketProgressView/*", timeout=8000)
            pool_urls.append(page.url)
            print(f"  Discovered Pool {n}: {page.url}")

            # Go back to the pool report for the next pool
            page.goto(
                page.url.rsplit("/bracketProgressView", 1)[0] + "/tournamentPoolReport",
                wait_until="domcontentloaded",
            )

        return pool_urls

    except Exception as e:
        print(f"  ! Auto-discovery failed: {e}")
        return []


def extract_games(page):
    """Extract game data from a bracketProgressView page.

    Playwright's CSS locator engine pierces shadow DOM automatically, so these
    selectors work even though the DEN app (Vaadin) renders inside shadow roots.
    """
    containers = page.locator(".mc-container")
    count = containers.count()
    games = []

    for i in range(count):
        c = containers.nth(i)
        full_text = c.inner_text().replace("\n", " ").strip()

        status_match = re.match(r"^(In progress|Pending|Completed)", full_text)
        status = status_match.group(1) if status_match else "unknown"

        court = ""
        court_el = c.locator(".mc-header-right")
        if court_el.count() > 0:
            court = court_el.first.inner_text().strip()

        top_row = c.locator(".mc-team-row-top")
        bottom_row = c.locator(".mc-team-row-bottom")

        def get_names(row):
            names_el = row.locator(".mc-team-item-names .mc-player-name")
            n = names_el.count()
            return [names_el.nth(j).inner_text().strip() for j in range(n)]

        top_names = get_names(top_row) if top_row.count() > 0 else []
        bottom_names = get_names(bottom_row) if bottom_row.count() > 0 else []

        top_fc = (
            top_row.locator(".mc-team-item-first-choice").count() > 0
            if top_row.count() > 0
            else False
        )
        bottom_fc = (
            bottom_row.locator(".mc-team-item-first-choice").count() > 0
            if bottom_row.count() > 0
            else False
        )

        games.append(
            {
                "game_number": i + 1,
                "status": status,
                "court": court,
                "top_names": top_names,
                "bottom_names": bottom_names,
                "top_fc": top_fc,
                "bottom_fc": bottom_fc,
            }
        )

    return games


def poll_once(page, pool_urls, cycle_label, logged_keys, today_str):
    """Poll every pool once. Returns (newly_logged_count, all_pools_done)."""
    newly_logged = 0
    all_pools_done = True

    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        for url in pool_urls:
            try:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(1200)
                games = extract_games(page)
            except Exception as e:
                print(f"  ! Failed to load {url}: {e}")
                all_pools_done = False
                continue

            if not games:
                print(f"  ! No games found on {url} (page may not have loaded correctly).")
                all_pools_done = False
                continue

            pool_done = True

            for g in games:
                key = (today_str, url, str(g["game_number"]))

                if key in logged_keys:
                    continue

                has_fc = g["top_fc"] or g["bottom_fc"]

                if not has_fc:
                    pool_done = False
                    continue

                if g["top_fc"]:
                    fc_names, other_names = g["top_names"], g["bottom_names"]
                else:
                    fc_names, other_names = g["bottom_names"], g["top_names"]

                fc_p1 = fc_names[0] if len(fc_names) > 0 else ""
                fc_p2 = fc_names[1] if len(fc_names) > 1 else ""
                other_p1 = other_names[0] if len(other_names) > 0 else ""
                other_p2 = other_names[1] if len(other_names) > 1 else ""

                detected_at = phoenix_now().strftime("%Y-%m-%d %H:%M:%S")

                writer.writerow(
                    [
                        today_str,
                        cycle_label,
                        url,
                        g["game_number"],
                        g["court"],
                        fc_p1,
                        fc_p2,
                        other_p1,
                        other_p2,
                        detected_at,
                    ]
                )
                logged_keys.add(key)
                newly_logged += 1
                pool_id = url.rstrip("/").split("/")[-1]
                print(
                    f"  + Logged: Pool {pool_id} Game {g['game_number']} "
                    f"({g['court'] or 'court TBD'}) FC -> {fc_p1} / {fc_p2}"
                )

            if not pool_done:
                all_pools_done = False

    return newly_logged, all_pools_done


def main():
    ensure_csv()
    logged_keys = load_logged_keys()

    print("FC Tracker starting -- fully automatic mode.")
    print(f"Will poll every {POLL_INTERVAL_SECONDS} seconds, up to {MAX_RUNTIME_MINUTES} minutes.")
    print("Press Ctrl+C at any time to stop.\n")

    start_time = time.monotonic()
    current_cycle_started = None
    current_pool_urls = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        if Path(SESSION_FILE).exists():
            context = browser.new_context(storage_state=SESSION_FILE)
        else:
            context = browser.new_context()

        page = context.new_page()

        if not Path(SESSION_FILE).exists():
            print("No saved session found. Log in manually in the browser window.")
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            input("Press Return here once you're logged in... ")
            context.storage_state(path=SESSION_FILE)

        try:
            while True:
                elapsed_minutes = (time.monotonic() - start_time) / 60
                if elapsed_minutes > MAX_RUNTIME_MINUTES:
                    print(f"\nReached {MAX_RUNTIME_MINUTES} minute safety cutoff. Stopping.")
                    break

                today_str = phoenix_now().strftime("%Y-%m-%d")
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Checking for an open shootout...")

                started = find_open_shootout(page)

                if started is None:
                    print("  No shootout currently Open. Will check again shortly.")
                    time.sleep(POLL_INTERVAL_SECONDS)
                    continue

                if started != current_cycle_started:
                    print(f"  New shootout detected (started {started}). Discovering pools...")
                    discovered = discover_pool_urls(page, started)

                    if not discovered:
                        print("  Auto-discovery failed for this shootout.")
                        discovered = get_pool_urls_manual()

                    if discovered:
                        current_cycle_started = started
                        current_pool_urls = discovered
                        print(f"  Now tracking {len(current_pool_urls)} pool(s) for shootout '{started}'.")
                    else:
                        print("  No pool URLs available. Will retry next check.")
                        time.sleep(POLL_INTERVAL_SECONDS)
                        continue

                cycle_label = f"Shootout {current_cycle_started}"
                newly_logged, all_done = poll_once(
                    page, current_pool_urls, cycle_label, logged_keys, today_str
                )

                if newly_logged:
                    print(f"  {newly_logged} new FC assignment(s) logged this check.")
                elif all_done:
                    print(f"  Cycle '{cycle_label}' fully captured. Watching for the next shootout.")
                else:
                    print("  No new FC assignments this check.")

                time.sleep(POLL_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            print("\nStopped by user.")

        context.storage_state(path=SESSION_FILE)
        browser.close()

    print(f"\nCSV saved at: {CSV_PATH.resolve()}")


if __name__ == "__main__":
    main()
