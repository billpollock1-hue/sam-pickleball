"""
Signup sheet monitor for Pickleball Den.
Run every 15 min via launchd. Tracks sign-ups and withdrawals per date.
"""

import csv
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

try:
    from generate_signup_viewer import generate_viewer as _generate_viewer
except ImportError:
    _generate_viewer = None

MT = ZoneInfo("America/Denver")
HOME_URL = "https://app.pickleballden.com"
LOOK_AHEAD_DAYS = 21  # search window: today through today+N

BASE_DIR = Path(__file__).parent
SESSION_FILE = BASE_DIR / "den_session.json"
STATE_FILE = BASE_DIR / "signup_monitor_state.json"
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)


# ── Utilities ───────────────────────────────────────────────────────────────

def now_mt():
    return datetime.now(MT)


def clean_name(name):
    return re.sub(r"\s+", " ", str(name).strip())


def format_den_date(d):
    return f"{d.month}/{d.day}/{d.year}"


def notify(message):
    subprocess.run(
        ["osascript", "-e", f'display notification "{message}" with title "Pickleball Den"'],
        capture_output=True,
    )


def is_sheet_open(date_str):
    """True if the 8 AM MT cutoff for this date hasn't passed yet."""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    cutoff = datetime(d.year, d.month, d.day, 8, 0, 0, tzinfo=MT)
    return now_mt() < cutoff


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"known_sheet_dates": [], "snapshots": {}}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def log_event(date_str, timestamp_str, action, player, signup_order, prior_order=None):
    log_file = LOGS_DIR / f"{date_str}_signup_log.csv"
    if not log_file.exists():
        log_file.write_text("timestamp_mt,action,player,signup_order,prior_order\n"
                            "# joined* = present when sheet was first discovered\n")
    player_escaped = player.replace('"', '""')
    prior_str = str(prior_order) if prior_order is not None else ""
    with log_file.open("a") as f:
        f.write(f'"{timestamp_str}","{action}","{player_escaped}",{signup_order},{prior_str}\n')


# ── Page parsing ─────────────────────────────────────────────────────────────

def extract_all_sheets(text):
    """
    Parse body text that may contain multiple expanded signup sheets.
    Returns {YYYY-MM-DD: [player_name, ...]} in signup order.
    Actual date line format: "Thu, Jun 25, 6:00AM-8:00AM MST"
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    today = now_mt().date()
    current_year = now_mt().year

    # Matches "Thu, Jun 25, 6:00AM-8:00AM MST" — group 1 = "Thu, Jun 25"
    date_pat = re.compile(r"([A-Z][a-z]{2},\s+[A-Z][a-z]{2}\s+\d{1,2}),\s+6:00AM")

    # Locate each sheet header in the line list
    sheet_starts = []
    for i, line in enumerate(lines):
        m = date_pat.search(line)
        if m:
            display = m.group(1)
            try:
                dt = datetime.strptime(f"{display} {current_year}", "%a, %b %d %Y")
                # Handle year rollover: if date appears to be in the past by >60 days, try next year
                if dt.date() < today - timedelta(days=60):
                    dt = dt.replace(year=current_year + 1)
                sheet_starts.append((i, dt.strftime("%Y-%m-%d")))
            except ValueError:
                pass

    if not sheet_starts:
        return {}

    sheets = {}
    for idx, (start_i, date_str) in enumerate(sheet_starts):
        end_i = sheet_starts[idx + 1][0] if idx + 1 < len(sheet_starts) else len(lines)
        section = lines[start_i:end_i]

        players = []
        seen = set()
        for j, line in enumerate(section):
            if re.match(r"^\d+\)\s+Member$", line) and j + 1 < len(section):
                name = clean_name(section[j + 1])
                key = name.lower()
                if name and key not in seen:
                    seen.add(key)
                    players.append(name)

        sheets[date_str] = players

    return sheets


# ── Browser interaction ───────────────────────────────────────────────────────

def fetch_all_sheets():
    """
    Navigate to the 6AM club's signup sheet view, expand all player lists,
    and return the full body text for parsing.

    Navigation path that works:
      Home → Sign-Ups (6AM club tab) → View Sign-Up Sheets
    This loads clubSignUpSheetView with the correct club context.

    Returns None if not logged in or navigation fails.
    """
    today = now_mt().date()
    end_date = today + timedelta(days=LOOK_AHEAD_DAYS)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        ctx_kwargs = {}
        if SESSION_FILE.exists():
            ctx_kwargs["storage_state"] = str(SESSION_FILE)
        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()

        try:
            page.goto(HOME_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)

            body = page.locator("body").inner_text()
            if "AAZPC DEN 6AM" not in body and "Sign-Ups" not in body:
                print("Session appears expired or home page didn't load. Skipping cycle.")
                return None

            # Step 1: open the Sign-Ups submenu on the 6AM club card
            page.locator("text=Sign-Ups").first.click()
            page.wait_for_timeout(2000)

            # Step 2: navigate into the signup sheet view for this club
            page.get_by_text("View Sign-Up Sheets", exact=True).click()
            page.wait_for_timeout(3000)

            body = page.locator("body").inner_text()
            if "Sign-Up Sheet View" not in body:
                print("Could not reach Sign-Up Sheet View. Skipping cycle.")
                return None

            # Optionally search a wider date window to catch upcoming new batches
            page.evaluate(f"""() => {{
                const pickers = document.querySelectorAll('vaadin-date-picker');
                if (pickers.length >= 2) {{
                    pickers[0].value = '{today.strftime("%Y-%m-%d")}';
                    pickers[1].value = '{end_date.strftime("%Y-%m-%d")}';
                }}
                const btns = [...document.querySelectorAll('vaadin-button')];
                const s = btns.find(b => b.textContent.trim().toLowerCase() === 'search');
                if (s) s.click();
            }}""")
            page.wait_for_timeout(3000)

            # Expand all "View Players" buttons — click .first in a loop because
            # each click changes the button to "Hide Players", shifting nth() offsets.
            for _ in range(30):
                vp = page.get_by_text("View Players", exact=True)
                if vp.count() == 0:
                    break
                try:
                    vp.first.click()
                    page.wait_for_timeout(800)
                except Exception:
                    break

            page.wait_for_timeout(1000)
            body_text = page.locator("body").inner_text()

        finally:
            try:
                context.storage_state(path=str(SESSION_FILE))
            except Exception:
                pass
            browser.close()

    return body_text


# ── Main monitor logic ────────────────────────────────────────────────────────

def run_monitor():
    ts = now_mt()
    timestamp_str = ts.strftime("%Y-%m-%d %H:%M:%S")

    print(f"\n[{timestamp_str} MT] Monitor cycle starting...")

    body_text = fetch_all_sheets()
    if body_text is None:
        return

    current_sheets = extract_all_sheets(body_text)

    if not current_sheets:
        print(f"[{timestamp_str}] No sheets found in search results.")
        return

    state = load_state()
    known = set(state.get("known_sheet_dates", []))
    snapshots = state.get("snapshots", {})

    # ── Detect new sheets ───────────────────────────────────────────────────
    new_dates = sorted(d for d in current_sheets if d not in known)
    if new_dates:
        state["known_sheet_dates"] = sorted(known | set(new_dates))
        label = ", ".join(new_dates)
        notify(f"New signup sheet(s): {label}")
        print(f"[{timestamp_str}] NEW SHEETS DETECTED: {label}")
        for d in new_dates:
            for order, player in enumerate(current_sheets[d], 1):
                log_event(d, timestamp_str, "joined*", player, order)
            # Pre-populate snapshot so the diff below doesn't re-log these as "joined"
            snapshots[d] = {
                "players": current_sheets[d],
                "last_checked": timestamp_str,
                "closed": False,
            }

    # ── Diff each sheet ─────────────────────────────────────────────────────
    dates_with_changes = set(new_dates)
    for date_str, players in current_sheets.items():
        if not is_sheet_open(date_str):
            snap = snapshots.get(date_str, {})
            if not snap.get("closed"):
                snapshots[date_str] = {**snap, "closed": True}
                print(f"[{timestamp_str}] Sheet {date_str} is now closed (past 8 AM MT).")
            continue

        prior = snapshots.get(date_str, {})
        prior_players = prior.get("players", [])
        prior_set = set(prior_players)
        current_set = set(players)

        joined = [p for p in players if p not in prior_set]
        withdrew = [p for p in prior_players if p not in current_set]

        # Guard against session-expiry false positives: if the majority of
        # known players vanish at once with no plausible replacements, the
        # page almost certainly returned empty/stale data.
        if prior_players and len(withdrew) > len(prior_players) * 0.5 and len(players) < len(prior_players) * 0.5:
            print(f"[{timestamp_str}] {date_str} SKIPPED — looks like session expiry "
                  f"({len(withdrew)} withdrew, only {len(players)} visible)")
            continue

        for player in joined:
            order = players.index(player) + 1
            log_event(date_str, timestamp_str, "joined", player, order)
            print(f"[{timestamp_str}] {date_str} JOINED  #{order:2d}: {player}")
            dates_with_changes.add(date_str)

        for player in withdrew:
            old_order = prior_players.index(player) + 1
            log_event(date_str, timestamp_str, "withdrew", player, old_order)
            print(f"[{timestamp_str}] {date_str} WITHDREW (was #{old_order:2d}): {player}")
            dates_with_changes.add(date_str)

        # Log reordered entries for players who moved up due to withdrawals
        if withdrew:
            for player in players:
                if player in prior_set:
                    new_order = players.index(player) + 1
                    old_order = prior_players.index(player) + 1
                    if new_order != old_order:
                        log_event(date_str, timestamp_str, "reordered", player, new_order, old_order)
                        print(f"[{timestamp_str}] {date_str} REORDERED {player}: #{old_order} → #{new_order}")

        snapshots[date_str] = {
            "players": players,
            "last_checked": timestamp_str,
            "closed": False,
        }

    state["snapshots"] = snapshots
    save_state(state)

    checked = [d for d in current_sheets if is_sheet_open(d)]
    print(f"[{timestamp_str}] Done. Open sheets checked: {checked}")

    if dates_with_changes and _generate_viewer:
        try:
            _generate_viewer()
            print(f"[{timestamp_str}] Updated signup_viewer.html")
        except Exception as e:
            print(f"[{timestamp_str}] Viewer update failed: {e}")

    open_changed = sorted(d for d in dates_with_changes if is_sheet_open(d))
    if open_changed:
        trigger_assignments_refresh(open_changed, timestamp_str)


def trigger_assignments_refresh(dates, timestamp_str):
    """Regenerate court assignments after signup changes (headless, in-runtime)."""
    script = BASE_DIR / "refresh_assignments.py"
    if not script.exists():
        print(f"[{timestamp_str}] refresh_assignments.py not deployed — skipping assignments refresh.")
        return
    env = {**os.environ, "PB_RUNTIME": str(BASE_DIR)}
    try:
        r = subprocess.run(
            [sys.executable, str(script), "--dates", *dates],
            env=env, cwd=str(BASE_DIR),
            capture_output=True, text=True, timeout=240,
        )
        if r.returncode == 0:
            notify(f"Court assignments updated: {', '.join(dates)}")
            print(f"[{timestamp_str}] Assignments refreshed: {', '.join(dates)}")
        else:
            print(f"[{timestamp_str}] Assignments refresh failed (rc={r.returncode}):\n"
                  f"{r.stdout[-400:]}\n{r.stderr[-400:]}")
    except Exception as e:
        print(f"[{timestamp_str}] Assignments refresh error: {e}")


def reconstruct_players_from_log(date_str):
    """Replay log events in order to get the last-known player list."""
    log_file = LOGS_DIR / f"{date_str}_signup_log.csv"
    if not log_file.exists():
        return []
    players = []
    with log_file.open(newline="") as f:
        for row in csv.reader(f):
            if not row or row[0].startswith("#") or row[0] == "timestamp_mt":
                continue
            if len(row) < 4:
                continue
            action, player = row[1], row[2]
            try:
                order = int(row[3])
            except (ValueError, IndexError):
                continue
            if action in ("joined*", "joined"):
                if player not in players:
                    players.insert(min(order - 1, len(players)), player)
            elif action == "withdrew":
                if player in players:
                    players.remove(player)
            elif action == "reordered":
                if player in players:
                    players.remove(player)
                    players.insert(min(order - 1, len(players)), player)
    return players


def patch_logs():
    """
    Reconcile open logs with the state file. Adds withdrew/joined/reordered
    entries for any gap between the last log entry and the current snapshot.
    Run with: python3 monitor_signups.py --patch
    """
    state = load_state()
    ts = now_mt().strftime("%Y-%m-%d %H:%M:%S")
    patched_any = False

    for date_str, snap in state.get("snapshots", {}).items():
        if snap.get("closed"):
            continue

        current_players = snap.get("players", [])
        log_players = reconstruct_players_from_log(date_str)

        current_set = set(current_players)
        log_set = set(log_players)

        withdrew = [p for p in log_players if p not in current_set]
        joined = [p for p in current_players if p not in log_set]

        if not withdrew and not joined:
            continue

        patched_any = True
        print(f"[patch] {date_str}: {len(withdrew)} withdrew, {len(joined)} joined")

        for player in withdrew:
            old_order = log_players.index(player) + 1
            log_event(date_str, ts, "withdrew", player, old_order)
            print(f"  withdrew {player} (was #{old_order})")

        for player in current_players:
            if player in log_set and player not in set(withdrew):
                new_order = current_players.index(player) + 1
                old_order = log_players.index(player) + 1
                if new_order != old_order:
                    log_event(date_str, ts, "reordered", player, new_order, old_order)
                    print(f"  reordered {player}: #{old_order} → #{new_order}")

        for player in joined:
            new_order = current_players.index(player) + 1
            log_event(date_str, ts, "joined", player, new_order)
            print(f"  joined {player} at #{new_order}")

    if not patched_any:
        print("[patch] All logs are already in sync with the state file.")


if __name__ == "__main__":
    import sys
    if "--patch" in sys.argv:
        patch_logs()
    else:
        run_monitor()
