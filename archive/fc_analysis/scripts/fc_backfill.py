"""
FC (First Choice) Historical Backfill for SAM Pickleball DEN shootouts.

One-time (or occasional) batch script: walks the ENTIRE Club Play List
history, and for every Completed shootout, follows the same click path a
person would (View Event -> Pool Report -> View Matches per pool) to reach
each pool's bracket page, then extracts every game's First Choice
assignment -- even though the shootout is long finished. The FC badge does
NOT disappear after completion, so this recovers full history in one pass
instead of needing live polling.

Appends to the same running CSV used by fc_tracker.py (output/fc_tracking.csv),
skipping any (date, pool_url, game_number) combination already present, so
it's safe to re-run without creating duplicates.

Run this from the same folder as den_assignments.py / fc_tracker.py so it
can reuse the saved login session (den_session.json).

USAGE:
    python3 fc_backfill.py

This does one full pass over the Club Play List and exits -- no polling loop.
"""

import csv
import re
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


def phoenix_now_str():
    return datetime.now(ZoneInfo("America/Phoenix")).strftime("%Y-%m-%d %H:%M:%S")


def ensure_csv():
    if not CSV_PATH.exists():
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADERS)


def load_logged_keys():
    keys = set()
    if not CSV_PATH.exists():
        return keys
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            keys.add((row["date"], row["pool_url"], row["game_number"]))
    return keys


def parse_started_date(started_text):
    """'July 2, 2026, 9:53 AM' -> '2026-07-02'. Falls back to raw text if parsing fails."""
    try:
        cleaned = re.sub(r",\s*\d{1,2}:\d{2}\s*[AP]M$", "", started_text).strip()
        dt = datetime.strptime(cleaned, "%B %d, %Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return started_text


def load_processed_cycle_labels():
    """Return set of cycle_label values already present in the CSV, so shootouts
    that were fully scraped in a previous run can be skipped entirely --
    no need to re-navigate through View Event / Pool Report / View Matches."""
    labels = set()
    if not CSV_PATH.exists():
        return labels
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            labels.add(row["cycle_label"])
    return labels


YEAR_CUTOFF = datetime(2025, 1, 1)


def parse_started_datetime(started_text):
    try:
        return datetime.strptime(started_text, "%B %d, %Y, %I:%M %p")
    except ValueError:
        return None


def get_shootout_rows_since_cutoff(page, cutoff=YEAR_CUTOFF):
    """The Club Play List is a virtualized Vaadin grid -- only ~20 rows are ever
    actually in the DOM at once, no matter how far you scroll the page body.
    This walks it using the grid's own scrollToIndex() API, harvesting newly
    visible rows at each step, until it's seen enough consecutive rows older
    than `cutoff` to be confident it's past the range we care about.
    """
    page.goto(LIST_CLUB_PLAY_URL, wait_until="domcontentloaded")

    try:
        page.get_by_text("Started", exact=True).first.wait_for(timeout=10000)
    except Exception:
        pass
    page.wait_for_timeout(1500)

    date_pattern = re.compile(r"^[A-Z][a-z]+ \d{1,2}, \d{4}, \d{1,2}:\d{2} [AP]M$")

    def harvest_visible_rows():
        text = page.locator("body").inner_text()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        rows = []
        for i, line in enumerate(lines):
            if date_pattern.match(line) and i + 1 < len(lines):
                next_line = lines[i + 1]
                if next_line in ("Open", "Completed"):
                    rows.append((line, next_line))
        return rows

    scroll_js = """(idx) => {
        function findAllShadow(root, selector, results) {
            results.push(...root.querySelectorAll(selector));
            root.querySelectorAll('*').forEach(el => { if (el.shadowRoot) findAllShadow(el.shadowRoot, selector, results); });
        }
        const grids = [];
        findAllShadow(document, 'vaadin-grid', grids);
        if (grids[0]) grids[0].scrollToIndex(idx);
    }"""

    collected = {}  # started_text -> status
    step = 15
    index = 0
    consecutive_misses = 0
    max_iterations = 400  # safety cap

    for _ in range(max_iterations):
        page.evaluate(scroll_js, index)
        page.wait_for_timeout(900)

        visible = harvest_visible_rows()
        if not visible:
            break

        any_new_in_range = False
        all_out_of_range = True

        for started, status in visible:
            if started in collected:
                continue
            dt = parse_started_datetime(started)
            if dt is None:
                continue
            if dt >= cutoff:
                collected[started] = status
                any_new_in_range = True
                all_out_of_range = False

        if all_out_of_range and not any_new_in_range:
            consecutive_misses += 1
        else:
            consecutive_misses = 0

        if consecutive_misses >= 3:
            break

        index += step

    # Sort by date descending -- since we collected a contiguous range from the
    # top of the (already date-descending) grid, each row's position in this
    # sorted list is a reliable approximation of its true grid index, which we
    # need later to scroll directly back to it instead of searching blindly.
    rows = sorted(
        collected.items(),
        key=lambda kv: parse_started_datetime(kv[0]) or datetime.min,
        reverse=True,
    )
    indexed_rows = [(i, started, status) for i, (started, status) in enumerate(rows)]
    return indexed_rows


def discover_pool_urls_for_row(page, started_timestamp, approx_index):
    """Same click path as fc_tracker.py's discover_pool_urls, reused for historical rows.

    A fresh page load resets the virtualized grid to show only the newest
    ~20 rows, so for anything further back we have to scroll to its
    approximate index first (using the same scrollToIndex() API) before the
    row even exists in the DOM to click.
    """
    scroll_js = """(idx) => {
        function findAllShadow(root, selector, results) {
            results.push(...root.querySelectorAll(selector));
            root.querySelectorAll('*').forEach(el => { if (el.shadowRoot) findAllShadow(el.shadowRoot, selector, results); });
        }
        const grids = [];
        findAllShadow(document, 'vaadin-grid', grids);
        if (grids[0]) grids[0].scrollToIndex(idx);
    }"""

    try:
        page.goto(LIST_CLUB_PLAY_URL, wait_until="domcontentloaded")
        try:
            page.get_by_text("Started", exact=True).first.wait_for(timeout=10000)
        except Exception:
            pass
        page.wait_for_timeout(800)

        target = page.get_by_text(started_timestamp, exact=True)
        found = False

        # Try the estimated index first, then nearby offsets in case the
        # estimate drifted slightly (e.g. an "Open" shootout completed and
        # shifted things by one during the run).
        for offset in (0, -10, 10, -20, 20, -40, 40):
            idx = max(0, approx_index + offset)
            page.evaluate(scroll_js, idx)
            page.wait_for_timeout(700)
            if target.count() > 0:
                found = True
                break

        if not found:
            print(f"  ! Could not locate row for {started_timestamp} near index {approx_index}.")
            return []

        target.first.click()
        page.wait_for_timeout(500)

        view_event = page.get_by_text("View Event", exact=True)
        if view_event.count() == 0:
            print(f"  ! Could not find 'View Event' for {started_timestamp}.")
            return []
        view_event.first.click()
        page.wait_for_url("**/tournamentPoolReport*", timeout=8000)
        page.wait_for_timeout(800)

        text = page.locator("body").inner_text()
        pool_numbers = sorted(set(int(n) for n in re.findall(r"Pool (\d+)", text)))

        if not pool_numbers:
            print(f"  ! No pools found for {started_timestamp}.")
            return []

        pool_urls = []
        for n in pool_numbers:
            page.goto(page.url, wait_until="domcontentloaded")
            page.wait_for_timeout(600)

            pool_label = page.get_by_text(f"Pool {n}", exact=True)
            if pool_label.count() == 0:
                continue
            pool_label.first.click()
            page.wait_for_timeout(500)

            view_matches = page.get_by_text("View Matches", exact=True)
            if view_matches.count() == 0:
                continue
            view_matches.first.click()
            page.wait_for_url("**/bracketProgressView/*", timeout=8000)
            pool_urls.append(page.url)

            page.goto(
                page.url.rsplit("/bracketProgressView", 1)[0] + "/tournamentPoolReport",
                wait_until="domcontentloaded",
            )

        return pool_urls

    except Exception as e:
        print(f"  ! Discovery failed for {started_timestamp}: {e}")
        return []


def extract_games(page):
    """Same extraction logic as fc_tracker.py -- Playwright's CSS engine pierces shadow DOM."""
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


def process_pool(page, pool_url, cycle_label, date_str, logged_keys, writer):
    newly_logged = 0
    try:
        page.goto(pool_url, wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        games = extract_games(page)
    except Exception as e:
        print(f"    ! Failed to load {pool_url}: {e}")
        return 0

    for g in games:
        key = (date_str, pool_url, str(g["game_number"]))
        if key in logged_keys:
            continue

        has_fc = g["top_fc"] or g["bottom_fc"]
        if not has_fc:
            continue

        if g["top_fc"]:
            fc_names, other_names = g["top_names"], g["bottom_names"]
        else:
            fc_names, other_names = g["bottom_names"], g["top_names"]

        fc_p1 = fc_names[0] if len(fc_names) > 0 else ""
        fc_p2 = fc_names[1] if len(fc_names) > 1 else ""
        other_p1 = other_names[0] if len(other_names) > 0 else ""
        other_p2 = other_names[1] if len(other_names) > 1 else ""

        writer.writerow(
            [
                date_str,
                cycle_label,
                pool_url,
                g["game_number"],
                g["court"],
                fc_p1,
                fc_p2,
                other_p1,
                other_p2,
                phoenix_now_str() + " (backfill)",
            ]
        )
        logged_keys.add(key)
        newly_logged += 1
        pool_id = pool_url.rstrip("/").split("/")[-1]
        print(
            f"    + Logged: Pool {pool_id} Game {g['game_number']} "
            f"({g['court'] or 'court n/a'}) FC -> {fc_p1} / {fc_p2}"
        )

    return newly_logged


def print_progress_bar(current, total, width=30):
    filled = int(width * current / total) if total else 0
    bar = "#" * filled + "-" * (width - filled)
    pct = (current / total * 100) if total else 0
    print(f"  [{bar}] {current}/{total} ({pct:.0f}%)")


def main():
    ensure_csv()
    logged_keys = load_logged_keys()
    processed_cycle_labels = load_processed_cycle_labels()
    total_new = 0
    total_skipped = 0

    print("FC Historical Backfill starting.\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        if Path(SESSION_FILE).exists():
            context = browser.new_context(storage_state=SESSION_FILE)
        else:
            context = browser.new_context()

        page = context.new_page()

        if not Path(SESSION_FILE).exists():
            print("No saved session found. In the browser window that just opened:")
            print("  1. Log in with your email and password.")
            print("  2. Click Play -> Shootout -> List Shootouts.")
            print("  3. Confirm you see the actual shootout list (not a 'Please log on' message).")
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            input("Press Return here once you're logged in... ")
            context.storage_state(path=SESSION_FILE)

        print("Scanning Club Play List for all shootouts since Jan 1, 2025 "
              "(this walks the virtualized grid and takes a minute or two)...\n")
        rows = get_shootout_rows_since_cutoff(page, cutoff=YEAR_CUTOFF)
        completed_rows = [(idx, started, status) for idx, started, status in rows if status == "Completed"]

        print(f"Found {len(rows)} shootouts since Jan 1, 2025 "
              f"({len(completed_rows)} Completed). This will take a while -- "
              f"grab a coffee.\n")

        with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            for progress_idx, (grid_idx, started, status) in enumerate(completed_rows, 1):
                date_str = parse_started_date(started)
                cycle_label = f"Shootout {started}"

                if cycle_label in processed_cycle_labels:
                    total_skipped += 1
                    print(f"[{progress_idx}/{len(completed_rows)}] {started} -- already scraped, skipping.")
                    print_progress_bar(progress_idx, len(completed_rows))
                    continue

                print(f"[{progress_idx}/{len(completed_rows)}] {started} ...")

                pool_urls = discover_pool_urls_for_row(page, started, grid_idx)
                if not pool_urls:
                    print("  ! No pools discovered, skipping.")
                    print_progress_bar(progress_idx, len(completed_rows))
                    continue

                for pool_url in pool_urls:
                    n = process_pool(page, pool_url, cycle_label, date_str, logged_keys, writer)
                    total_new += n

                print_progress_bar(progress_idx, len(completed_rows))

        context.storage_state(path=SESSION_FILE)
        browser.close()

    print(f"\nBackfill complete. {total_new} new FC assignment(s) logged. "
          f"{total_skipped} shootout(s) skipped (already scraped).")
    print(f"CSV saved at: {CSV_PATH.resolve()}")


if __name__ == "__main__":
    main()
