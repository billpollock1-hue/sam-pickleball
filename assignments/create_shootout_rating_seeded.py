"""
create_shootout.py

Automates the morning shootout creation flow on Pickleball Den, replacing
the manual 4 AM MST / 6 AM CDT routine:

  1. Open today's signup sheet.
  2. Trim excess players (remove from the bottom of signup order until the
     count is a multiple of 4).
  3. Create the shootout (set Number of Courts, leave every other field
     at its existing default).
  4. Check In All.
  5. Audit DEN's own Step/% seeding against a computed ground truth, and
     correct any Ladder Step box where DEN disagrees -- including
     "Den New Player Tryout" mis-seeds.
  6. Seed Players.
  7. Start Event.

RATING-SEEDED VARIANT: this version seeds courts using the model's
player ratings (assign_courts_by_rating / load_player_ratings) instead of
DEN's own Step/% system (assign_courts). Since DEN's Ladder Step field
only understands its own Step numbers -- not raw model ratings -- the
audit writes a SYNTHETIC Step value per player: the top PLAYERS_PER_COURT
-ranked players (by rating) get Step 1, the next PLAYERS_PER_COURT get
Step 2, and so on. This reuses DEN's own "Seed Players" grouping logic
(which seeds courts strictly off Ladder Step) to produce courts matching
the model's ranking, without DEN ever needing to know the model's actual
rating scale. This is a test/comparison run against a day whose real 6 AM
shootout already completed -- results won't be posted, and the shootout
will be deleted after confirming it starts correctly.

Reuses helpers from den_assignments.py rather than re-deriving them:
  - next_weekday_date, format_den_date
  - automate_signup_search
  - extract_signup_names_from_text, extract_play_date
  - extract_ratings_from_text
  - assign_courts_by_rating, load_player_ratings (ground truth for the
    rating-based seeding this variant writes into DEN's Step field)
  - ensure_model_current
  - clean_name
  - save_page_text (for debug screenshots/text dumps on failure)

This script is intentionally separate from den_assignments.py's main():
that flow is the read-only reporting/viewer pipeline; this one performs
write-back actions against DEN, so it gets its own entry point, its own
debug output, and its own launchd job.
"""

import json
import re
import sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# Reuse everything already proven in den_assignments.py rather than
# re-deriving selectors/logic that already works.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from den_assignments import (
    SIGNUP_URL,
    RATINGS_URL,
    SESSION_FILE,
    OUT_DIR,
    PLAYERS_PER_COURT,
    format_den_date,
    automate_signup_search,
    extract_signup_names_from_text,
    extract_play_date,
    extract_ratings_from_text,
    assign_courts_by_rating,
    load_player_ratings,
    ensure_model_current,
    clean_name,
    save_page_text,
)


def todays_date():
    """
    Unlike den_assignments.py's next_weekday_date() -- which rolls forward
    to the next weekday after 5:55 AM since that script is a reporting tool
    often run later in the day -- shootout creation must always target
    TODAY's Arizona-time sheet. DEN does not allow creating a shootout
    against a future-dated sign-up sheet, so there is no "roll forward"
    case here at all.
    """
    return datetime.now(ZoneInfo("America/Phoenix")).date()

DEBUG_DIR = OUT_DIR / "debug" / "create_shootout"
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

HEADLESS = True  # flip to False for live selector testing against the real app


def _debug_screenshot(page, name):
    """Best-effort screenshot for diagnosing an unattended run after the fact."""
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = DEBUG_DIR / f"{name}_{ts}.png"
        page.screenshot(path=str(path))
        print(f"  (debug screenshot saved: {path})")
    except Exception:
        pass


def _confirm_yes(page, label_hint=""):
    """
    Click the 'Yes' confirmation on DEN's are-you-sure popups.
    These have consistently been in-page modals (not native browser
    confirm() dialogs) elsewhere in this app, so we look for a clickable
    'Yes' text node. If this turns out to be a native dialog for a
    particular screen, wire a page.on('dialog', ...) handler for that
    specific action instead.

    NOTE: force=True was tried here previously and removed -- it only
    bypasses Playwright's own actionability checks, not the browser's real
    hit-testing. If a genuine overlay sits on top, the browser still
    delivers the click to whatever's actually on top, so force=True can
    report success while clicking the wrong thing entirely (confirmed
    live: this produced a false "removed" success message while DEN's
    live signup sheet was left unchanged).

    Live debugging resolved the real cause: a genuine mouse click DOES
    work correctly on these dialogs -- Playwright's plain .click() was
    only being blocked by its own conservative "is this covered?"
    pre-check, not by anything that would actually stop a real click.
    page.mouse.click() at the button's real coordinates is a genuine,
    trusted click that skips only that pre-check, unlike force=True
    (which bypasses the check but still risks landing on whatever's
    visually on top) or other synthetic-event techniques (which this app
    doesn't reliably treat the same as a real click).
    """
    try:
        yes_button = page.get_by_text("Yes", exact=True)
        yes_button.wait_for(state="visible", timeout=5000)
        box = yes_button.bounding_box()
        if box is None:
            raise PWTimeout("Yes button has no bounding box")
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.wait_for_timeout(800)
    except (PWTimeout, Exception):
        print(f"  ⚠ No 'Yes' confirmation appeared after {label_hint or 'action'} "
              f"-- it may not have required confirmation, or the popup text differs.")


def automate_signup_search_today(page):
    """
    Local replacement for den_assignments.automate_signup_search() --
    that function searches next_weekday_date(), which rolls forward past
    5:55 AM since it's built for the reporting flow. This script must
    always search today's Arizona-time date, since DEN won't let you
    create a shootout against a future sheet. Same search/View Players
    mechanics as the original, just pinned to today.
    """
    import re as _re

    target_date = todays_date()
    target_text = format_den_date(target_date)

    print(f"\nSearching signup sheet for TODAY: {target_text}")

    try:
        # Target each date field by its label rather than input position --
        # positional indexing (inputs.nth(0)/.nth(1)) was unreliable here:
        # live debugging showed "Date Range End" silently reverting to a
        # stale default (8/4/2026) instead of receiving today's date. The
        # page's rendered <label for="input-vaadin-date-picker-N"> ids
        # (29, 30) indicate this Vaadin SPA likely keeps other views/inputs
        # mounted in the DOM even when not visible, so a positional input
        # count is not a reliable proxy for "the two visible date fields."
        # get_by_label resolves the correct field regardless of how many
        # other inputs exist elsewhere in the DOM.
        start_field = page.get_by_label("Date Range Start", exact=True)
        end_field = page.get_by_label("Date Range End", exact=True)
        start_field.wait_for(timeout=8000)

        # These are Vaadin date-picker comboboxes, not plain text inputs --
        # clicking one opens a calendar overlay that then sits on top of the
        # page and blocks clicks elsewhere (confirmed via check_no_shootout.py
        # hitting a 30s timeout here: "<html>...intercepts pointer events").
        # Pressing Escape after filling each field closes that overlay before
        # the next field is touched, instead of leaving it open to block it.
        #
        # Date Range End has repeatedly reverted to a stale auto-computed
        # default (Start + 21 days) even after being explicitly filled --
        # live evidence: Start correctly showed 7/14/2026 but End still
        # showed 8/4/2026, and "9 Sign-Up Sheets found" confirmed the
        # search really did span the full 3-week window rather than just
        # today. This looks like DEN's widget re-asserting a linked
        # Start+21-days default on End sometime after our fill, rather
        # than a wrong-field/selector problem (get_by_label already
        # confirmed it targets the correct element). Fill Start first,
        # give any auto-link default time to fire, THEN fill End last --
        # and verify/retry rather than trust a single fill to stick.
        start_field.click()
        start_field.press("Meta+A")
        start_field.fill(target_text)
        start_field.press("Escape")
        page.wait_for_timeout(600)

        # Confirmed live (three retries, identical result every time,
        # even immediately after fill+readback): Date Range End reverts
        # to EXACTLY Start + 21 days no matter what's typed into it. This
        # isn't a timing/async issue -- the widget enforces End = Start+21
        # as a hard computed constraint that can't be overridden through
        # normal interaction. Rather than keep fighting it, accept the
        # wider window; the correct sheet gets found afterward by its own
        # visible date heading instead of by narrowing the search.
        end_field.click()
        end_field.press("Meta+A")
        end_field.fill(target_text)
        end_field.press("Escape")
        page.wait_for_timeout(500)

        # Two elements match the text "Search" -- the top nav's Search tab
        # and the actual Search button. get_by_text can't disambiguate
        # (Playwright's own strict-mode error confirmed both matches);
        # get_by_role targets the button specifically, since the nav item
        # is a "tab" and this is a "button".
        #
        # Hardened with an explicit wait_for(state="visible") before the
        # click, rather than relying solely on Playwright's default 30s
        # actionability timeout -- confirmed live (2026-07-17) that DEN's
        # page can still be settling early in the morning (2:33/2:38 AM
        # MST), causing "Locator.click: Timeout 30000ms exceeded" on this
        # exact button twice in a row before a third attempt (unchanged
        # code) succeeded minutes later. A longer, explicit wait here
        # gives slow-loading mornings more room to succeed on the first
        # try instead of relying on the poller's 5-minute retry to paper
        # over it.
        search_button = page.get_by_role("button", name="Search", exact=True)
        search_button.wait_for(state="visible", timeout=45000)
        search_button.click()
        page.wait_for_timeout(2500)

    except Exception as e:
        raise RuntimeError(f"Automatic date/search step failed: {e}")

    try:
        body_text = page.locator("body").inner_text()
        if "Hide Players" in body_text and _re.search(r"\d+\)\s+Member", body_text):
            print("View Players already appears to be open.")
            return

        # Since the search window can't be narrowed to a single day (see
        # above), multiple sign-up sheets/dates come back. Locate today's
        # specific card by its own visible date heading (e.g. "Jul 14")
        # and click the "View Players" link that immediately follows it
        # in document order -- each date's card, including its own View
        # Players link, is grouped together before the next date's card
        # begins, so the nearest following match belongs to today.
        heading_fragment = target_date.strftime("%b %-d")  # e.g. "Jul 14"
        view_players_link = page.locator(
            f"xpath=(//*[contains(normalize-space(text()), '{heading_fragment}')])[1]"
            f"/following::*[contains(normalize-space(text()), 'View Players')][1]"
        )
        view_players_link.click(timeout=10000)
        page.wait_for_timeout(1200)

    except Exception as e:
        raise RuntimeError(f"Could not automatically open View Players: {e}")


def _write_auto_removal_marker(play_date_file, names_removed):
    """
    Signal to monitor_signups.py that these names were removed by the
    launcher, not by the players themselves -- so the signup log can
    tag the resulting withdrawal as "removed_auto" instead of "withdrew".

    Absolute repo path (not derived from this script's own location),
    same reasoning as REPO_ASSIGNMENTS_DIR / REPO_ROOT elsewhere in this
    codebase: this script runs from two different locations, but the
    marker file needs to live somewhere both this script and
    monitor_signups.py can always find it regardless of which copy of
    either script is running.
    """
    if not names_removed:
        return
    marker_path = Path("/Users/billpollock/Documents/SAM Pickleball/sam-pickleball/data/last_auto_removal.json")
    try:
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text(json.dumps({
            "date": play_date_file,
            "players": names_removed,
            "timestamp": datetime.now(ZoneInfo("America/Phoenix")).isoformat(),
        }))
    except Exception as e:
        print(f"  ⚠ Could not write auto-removal marker: {e}")


def determine_excess_players(signups):
    """
    Mirrors assign_courts()'s eligibility split, but returns just the
    names that need to be removed from the DEN signup sheet -- last
    signups first, trimmed down to a multiple of PLAYERS_PER_COURT.
    """
    total = len(signups)
    eligible_count = (total // PLAYERS_PER_COURT) * PLAYERS_PER_COURT
    excess = signups.iloc[eligible_count:].copy()
    return excess["Player"].tolist()


def remove_excess_players(page, names_to_remove):
    if not names_to_remove:
        print("Player count is already a multiple of 4 -- no removals needed.")
        return

    print(f"Removing {len(names_to_remove)} excess player(s): {', '.join(names_to_remove)}")

    # Same multi-sheet ambiguity as Remove Players / View Players above --
    # scope to the card that follows today's own date heading in document
    # order.
    heading_fragment = todays_date().strftime("%b %-d")  # e.g. "Jul 14"

    try:
        remove_players_link = page.locator(
            f"xpath=(//*[contains(normalize-space(text()), '{heading_fragment}')])[1]"
            f"/following::*[contains(normalize-space(text()), 'Remove Players')][1]"
        )
        remove_players_link.click(timeout=5000)
        # The "Select Player To Remove" popup is a vaadin-dialog-overlay
        # (with-backdrop). Give it time to fully settle before interacting.
        page.wait_for_timeout(2000)

        # Opened ONCE, outside the per-name loop -- confirmed live that
        # this dialog intentionally stays open across multiple removals
        # (its own already-rendered list does NOT refresh itself after
        # each removal, which is normal/expected here, not a failure
        # signal). Re-clicking "Remove Players" for each name isn't
        # necessary or correct.
        dialog = page.get_by_role("dialog")

        for name in names_to_remove:
            # The removal dialog only ever shows the player's plain name --
            # e.g. "Tonya Carroll" -- even when the signup list elsewhere
            # tags them as "Tonya Carroll (Wait List)". Searching the dialog
            # for the full tagged string never matches and hangs until
            # timeout. Strip any trailing parenthetical before searching
            # here; the original (possibly tagged) name is still what gets
            # logged and returned to the caller.
            search_name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()

            # RESOLVED via live testing: force=True, dispatch_event, and
            # el.click() via JS are all recognizably synthetic/untrusted
            # events that this app doesn't treat the same as a real click.
            # A genuine mouse click on the player's name DOES work
            # correctly and instantly -- Playwright's plain .click() only
            # times out here because of its own conservative "is this
            # covered?" pre-check flagging the dialog's overlay, not
            # because a real click wouldn't land. page.mouse.click(x, y)
            # issues a genuine, trusted click at the element's real
            # screen coordinates, skipping only that pre-check.
            #
            # Scoped to the dialog specifically -- the underlying signup
            # list stays in the DOM (just visually covered), so an
            # unscoped page-wide search can match the same name twice.
            target = dialog.get_by_text(search_name, exact=True)
            if target.count() == 0:
                target = dialog.get_by_text(search_name, exact=False).first

            box = target.bounding_box()
            if box is None:
                raise RuntimeError(
                    f"Could not get bounding box for '{search_name}' "
                    f"(from '{name}') in the Select Player To Remove popup "
                    f"-- element may not be visible/rendered."
                )
            center_x = box["x"] + box["width"] / 2
            center_y = box["y"] + box["height"] / 2
            page.mouse.click(center_x, center_y)

            # CONFIRMED live via screenshot: DEN shows an "Are you sure
            # you want to remove {name} from this Sign-Up Sheet?" dialog
            # with Yes/No buttons after selecting a name -- this step was
            # previously dropped based on uncertain memory of a manual
            # test, which was wrong. Click Yes using the same proven
            # mouse.click() technique.
            page.wait_for_timeout(500)
            yes_button = page.get_by_role("button", name="Yes", exact=True)
            try:
                yes_box = yes_button.bounding_box()
                if yes_box is None:
                    raise RuntimeError("Yes button has no bounding box")
                page.mouse.click(
                    yes_box["x"] + yes_box["width"] / 2,
                    yes_box["y"] + yes_box["height"] / 2,
                )
            except Exception as e:
                raise RuntimeError(
                    f"Could not click Yes to confirm removing {name}: {e}"
                )

            # DEN's real success signal for this action is a toast
            # notification -- "Player removed from Sign-Up Sheet" --
            # confirmed live via screenshot. NOT the dialog closing, and
            # NOT its own list updating (it doesn't, by design). Treating
            # "dialog still open" as failure was actively wrong -- that
            # is the dialog's normal, expected behavior when supporting
            # sequential multi-player removal, and the earlier version
            # of this code incorrectly raised an error on a genuinely
            # successful removal. Wait for this toast as the definitive
            # per-name success signal instead.
            try:
                page.get_by_text(
                    "Player removed from Sign-Up Sheet", exact=False
                ).wait_for(state="visible", timeout=5000)
                print(f"  ✓ {name}: DEN confirmed removal (toast message seen)")
            except PWTimeout:
                raise RuntimeError(
                    f"No 'Player removed from Sign-Up Sheet' confirmation "
                    f"appeared after clicking {name} -- the click may not "
                    f"have genuinely registered with DEN."
                )

            page.wait_for_timeout(500)

        # Close the dialog (its own list is known-stale after removals --
        # don't scrape it) and verify the REAL underlying signup list
        # reflects every removal, all at once, after all names are done.
        page.keyboard.press("Escape")
        page.wait_for_timeout(800)

        verify_text = page.locator("body").inner_text()
        current_signups = extract_signup_names_from_text(verify_text)

        if current_signups.empty:
            raise RuntimeError(
                "Could not verify removals -- re-scraping the signup sheet "
                "after all removal attempts returned no parseable players "
                "at all. Stopping rather than trusting an empty/broken scrape."
            )

        still_present = []
        for name in names_to_remove:
            clean_name = name.replace(" (Wait List)", "").strip()
            if clean_name in current_signups["Player"].values:
                still_present.append(name)

        if still_present:
            raise RuntimeError(
                f"{', '.join(still_present)} still appear on the live signup "
                f"sheet after the removal flow completed -- DEN did not "
                f"actually process the removal for at least one player. "
                f"Stopping rather than silently proceeding with the wrong "
                f"player count."
            )

        print(f"  ✓ All {len(names_to_remove)} player(s) confirmed removed "
              f"(verified against live signup sheet)")

    except Exception as e:
        print(f"  ⚠ Failed to remove excess players: {e}")
        _debug_screenshot(page, "remove_players_failure")
        raise RuntimeError(
            f"Could not remove excess players -- stopping rather than "
            f"creating a shootout with the wrong player count."
        )


def create_shootout(page, num_courts):
    print(f"Creating shootout with {num_courts} court(s)...")

    # Same multi-sheet ambiguity as Remove Players / View Players above --
    # scope to today's card via its date heading rather than a page-wide
    # match, since the search window still contains every date through
    # Start+21 days.
    heading_fragment = todays_date().strftime("%b %-d")  # e.g. "Jul 14"
    create_shootout_link = page.locator(
        f"xpath=(//*[contains(normalize-space(text()), '{heading_fragment}')])[1]"
        f"/following::*[contains(normalize-space(text()), 'Create Shootout')][1]"
    )
    create_shootout_link.click(timeout=5000)
    page.wait_for_timeout(1000)

    # "Number of Courts" is the only field this script touches; every other
    # field (Match Type, Moves Players, Self Check-In Code, Merge Sign-Up
    # Sheet, Five Player Pools, Format, Team Type) is left at whatever DEN
    # already has set, per the documented manual routine.
    try:
        courts_label = page.get_by_text("Number of Courts", exact=False)
        courts_input = courts_label.locator(
            "xpath=following::input[1]"
        )
        courts_input.click()
        courts_input.press("Meta+A")
        courts_input.fill(str(num_courts))
        courts_input.press("Tab")
    except Exception as e:
        _debug_screenshot(page, "create_shootout_courts_field")
        raise RuntimeError(f"Could not set Number of Courts field: {e}")

    # Same ambiguity pattern as the earlier "Search" button fix -- the
    # page has both an <h2>Create Shootout</h2> heading and the actual
    # submit button, and exact=False matches case-insensitively, so both
    # matched. get_by_role targets the button specifically.
    page.get_by_role("button", name="Create Shootout", exact=True).click(timeout=5000)
    page.wait_for_timeout(1200)

    # "Sign-up sheet is still available for additional players" guard popup
    # -- ignore and proceed, per the documented routine.
    try:
        page.get_by_text("Yes", exact=True).click(timeout=3000)
        page.wait_for_timeout(800)
    except PWTimeout:
        pass  # popup didn't appear this time -- fine, nothing to dismiss


def check_in_all(page):
    print("Checking in all players...")
    page.get_by_text("Check-In All", exact=True).click(timeout=5000)
    page.wait_for_timeout(500)
    _confirm_yes(page, label_hint="Check-In All")
    page.wait_for_timeout(1000)


def read_ladder_step_grid(page, known_player_names):
    """
    Scrape the current player-name -> Ladder Step box mapping from the
    Shootout Check-In screen.

    CONFIRMED via live DOM inspection: this screen is a <vaadin-grid>
    custom element, NOT a plain HTML <table> -- there is no <tr>/<td>
    structure anywhere. Cells are rendered as numbered
    vaadin-grid-cell-content slots, and the editable Ladder Step value
    lives inside a <vaadin-number-field>'s shadow DOM as a real
    <input type="number">. Playwright pierces shadow DOM automatically,
    so a direct selector reaches it without any special handling.

    Vaadin's internal cell-content slot numbering is an implementation
    detail, not a stable semantic column mapping -- rather than parse
    it, this pairs each <vaadin-number-field> (the Step column, in
    top-to-bottom row order) with the player name found in the same
    row order among the grid's text cells, matched against
    known_player_names (from computed_assignments) so unrelated text
    cells (e.g. the "Assigned Pool" column) don't get mistaken for a
    name.
    """
    # Vaadin Grid virtualizes rows -- it may only render what's currently
    # visible/settled into the DOM, not the full list, especially right
    # after the screen loads. If this query ran before the grid finished
    # rendering, both counts could come back as 0 and silently "match" at
    # zero, producing an empty result without any mismatch warning. Wait
    # for at least one Ladder Step input to actually exist first.
    try:
        page.locator("vaadin-number-field input[type='number']").first.wait_for(
            state="attached", timeout=8000
        )
    except Exception:
        print("  ⚠ No Ladder Step inputs appeared on the page at all "
              "within 8s -- grid may not have rendered.")
        return pd.DataFrame()

    step_inputs = page.locator("vaadin-number-field input[type='number']")
    step_count = step_inputs.count()

    name_cells = page.locator("vaadin-grid-cell-content")
    name_cell_count = name_cells.count()

    print(f"  DIAGNOSTIC: found {step_count} Ladder Step input(s) and "
          f"{name_cell_count} vaadin-grid-cell-content element(s) total.")

    ordered_names = []
    for i in range(name_cell_count):
        try:
            text = clean_name(name_cells.nth(i).inner_text())
        except Exception:
            continue
        if text and text in known_player_names:
            ordered_names.append(text)

    print(f"  DIAGNOSTIC: matched {len(ordered_names)} player name(s) "
          f"against known_player_names: {ordered_names}")

    if len(ordered_names) != step_count:
        print(f"  ⚠ Found {len(ordered_names)} matching player name(s) but "
              f"{step_count} Step input(s) -- counts don't line up, so "
              f"positional pairing isn't safe. Skipping audit.")
        return pd.DataFrame()

    grid = []
    for name, i in zip(ordered_names, range(step_count)):
        try:
            step_input = step_inputs.nth(i)
            raw_value = step_input.input_value()
            if not raw_value.strip():
                # DOM inspection earlier showed placeholder="1" rather
                # than a set value -- DEN may be displaying these numbers
                # as placeholder text, not actual input values, which
                # would make input_value() return "" for every row.
                raw_value = step_input.get_attribute("placeholder") or ""
            step_value = int(raw_value.strip())
        except Exception as e:
            print(f"  DIAGNOSTIC: failed reading Step input {i} for "
                  f"{name!r}: {type(e).__name__}: {e}")
            continue
        grid.append({
            "Player": name,
            "Step_den": step_value,
            "_locator": step_input,
        })

    return pd.DataFrame(grid)


def cross_check_and_correct_seeding(page, computed_assignments):
    """
    computed_assignments: a DataFrame with at least ["Player", "Step"]
    columns representing the ground truth to seed courts by.

    RATING-SEEDED VARIANT: "Step" here is a SYNTHETIC group number
    derived from the rating-based ranking (top PLAYERS_PER_COURT players
    get Step 1, next PLAYERS_PER_COURT get Step 2, etc.) -- not DEN's
    real Step/% value. DEN's "Seed Players" groups courts strictly off
    this Ladder Step field, so writing our rating-derived group number
    here makes DEN produce courts matching the rating ranking, without
    DEN needing to understand the model's actual rating scale.

    This function audits every row DEN seeded and overwrites only the
    ones that disagree with computed_assignments.

    Vaadin's virtualized grid can silently under-render (fewer rows in
    the DOM than players actually eligible) right after the screen
    loads -- confirmed live on two separate real runs, producing 11
    rows for a 12-player group each time and dropping a DIFFERENT
    player each time, with no warning (the old check only compared the
    grid against itself, not against the true eligible count).
    expected_count guards against this: if the grid renders short, we
    scroll to force the rest into the DOM and retry once; if it's
    still short after that, we abort rather than seed/start an event
    with an unaudited player.
    """
    print("Auditing DEN's seeding against computed Step values...")

    known_player_names = set(computed_assignments["Player"].apply(clean_name))
    expected_count = len(computed_assignments)

    grid = read_ladder_step_grid(page, known_player_names)

    attempts = 0
    while len(grid) < expected_count and attempts < 2:
        attempts += 1
        print(f"  ⚠ Grid returned {len(grid)} row(s) but {expected_count} "
              f"player(s) are eligible -- Vaadin's virtualized grid likely "
              f"under-rendered. Scrolling and retrying (attempt {attempts})...")
        try:
            # CONFIRMED live: a JS-set scrollTop on the <vaadin-grid> host
            # element was a silent no-op (before/after reads were
            # byte-identical) -- the real scrollable node is almost
            # certainly inside shadow DOM. Real, trusted mouse-wheel events
            # at the grid's actual screen location sidestep that entirely,
            # same "genuine input" approach already proven for the removal
            # click elsewhere in this file.
            grid_el = page.locator("vaadin-grid").first
            box = grid_el.bounding_box()
            if box:
                center_x = box["x"] + box["width"] / 2
                center_y = box["y"] + box["height"] / 2
                page.mouse.move(center_x, center_y)
                for _ in range(6):
                    page.mouse.wheel(0, 400)
                    page.wait_for_timeout(200)
        except Exception as e:
            print(f"    (scroll attempt failed: {e})")
        page.wait_for_timeout(2000 + attempts * 1000)
        grid = read_ladder_step_grid(page, known_player_names)

    if grid.empty:
        print("  ⚠ Could not read the Ladder Step grid -- skipping seeding audit.")
        _debug_screenshot(page, "ladder_step_grid_empty")
        return

    if len(grid) < expected_count:
        missing = known_player_names - set(grid["Player"])
        _debug_screenshot(page, "ladder_step_grid_undercount")
        raise RuntimeError(
            f"Ladder Step grid only rendered {len(grid)} of {expected_count} "
            f"eligible player(s) even after a retry -- stopping rather than "
            f"seeding/starting an event with unaudited player(s): "
            f"{', '.join(sorted(missing))}"
        )

    ground_truth = computed_assignments[["Player", "Step"]].copy()
    ground_truth["Player"] = ground_truth["Player"].apply(clean_name)

    merged = grid.merge(ground_truth, on="Player", how="left")

    unmatched = merged[merged["Step"].isna()]
    if not unmatched.empty:
        print(f"  ⚠ {len(unmatched)} player(s) on the Check-In grid had no computed "
              f"Step value -- leaving DEN's value untouched for: "
              f"{', '.join(unmatched['Player'].tolist())}")

    to_fix = merged[merged["Step"].notna() & (merged["Step_den"] != merged["Step"])]

    if to_fix.empty:
        print("  ✓ DEN's seeding matched the computed values for every player.")
        return

    print(f"  Correcting {len(to_fix)} mis-seeded player(s):")
    for _, row in to_fix.iterrows():
        try:
            box = row["_locator"]
            box.click()
            box.press("Meta+A")
            box.fill(str(int(row["Step"])))
            box.press("Tab")
            print(f"    {row['Player']}: Step {row['Step_den']} → {int(row['Step'])}")
        except Exception as e:
            print(f"    ⚠ Failed to correct {row['Player']}: {e}")


def seed_players(page):
    print("Seeding players...")
    page.get_by_text("Seed Players", exact=True).click(timeout=5000)
    page.wait_for_timeout(500)
    _confirm_yes(page, label_hint="Seed Players")
    page.wait_for_timeout(1500)  # allow "Shootout seeded" toast to clear


def start_event(page):
    print("Starting event...")
    page.get_by_text("Start Event", exact=True).click(timeout=5000)
    page.wait_for_timeout(500)
    _confirm_yes(page, label_hint="Start Event")
    page.wait_for_timeout(1500)


def main():
    print(f"\n=== Automated Shootout Creation (Modified ELO seeding): "
          f"{datetime.now(ZoneInfo('America/Phoenix')).strftime('%A, %B %d, %Y %I:%M %p MST')} ===\n")

    ensure_model_current()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)

        if Path(SESSION_FILE).exists():
            context = browser.new_context(storage_state=SESSION_FILE)
        else:
            context = browser.new_context()

        page = context.new_page()

        try:
            print("Opening signup sheet...")
            page.goto(SIGNUP_URL, wait_until="domcontentloaded")
            automate_signup_search_today(page)

            signup_text = save_page_text(page, "signup_page_create.txt")
            play_date_display, play_date_file = extract_play_date(signup_text)
            signups = extract_signup_names_from_text(signup_text)

            print(f"Found {len(signups)} signup(s) for {play_date_display}.")
            if signups.empty:
                raise RuntimeError("No signups detected -- aborting rather than "
                                    "creating an empty/wrong shootout.")

            excess_names = determine_excess_players(signups)
            remove_excess_players(page, excess_names)
            _write_auto_removal_marker(play_date_file, excess_names)

            eligible_count = len(signups) - len(excess_names)
            num_courts = eligible_count // PLAYERS_PER_COURT
            print(f"Eligible players: {eligible_count} -> {num_courts} court(s).")

            print("Loading model ratings for the seeding audit...")
            player_ratings = load_player_ratings()
            if player_ratings.empty:
                raise RuntimeError("No model ratings available -- aborting rather "
                                    "than seeding with an empty rating table.")

            eligible_signups = signups.iloc[:eligible_count].copy()
            rating_assignments, _ = assign_courts_by_rating(eligible_signups, player_ratings)

            # rating_assignments already has a "Court" column from
            # assign_courts_by_rating (STARTING_COURT + index // PLAYERS_PER_COURT).
            # Convert that into a synthetic Step group number starting at 1:
            # top PLAYERS_PER_COURT-ranked players -> Step 1, next -> Step 2, etc.
            computed_assignments = rating_assignments.copy()
            computed_assignments["Step"] = (
                computed_assignments["Court"] - computed_assignments["Court"].min() + 1
            )

            # Back to the signup sheet to actually create the shootout.
            page.goto(SIGNUP_URL, wait_until="domcontentloaded")
            automate_signup_search_today(page)

            create_shootout(page, num_courts)
            check_in_all(page)
            cross_check_and_correct_seeding(page, computed_assignments)
            seed_players(page)
            start_event(page)

            context.storage_state(path=SESSION_FILE)
            print(f"\n✓ Shootout created and started for {play_date_display} "
                  f"(Modified ELO seeding).")
            print(f"LAUNCH_RESULT: {json.dumps({'players_removed': excess_names})}")

        except Exception as e:
            print(f"\n✗ Automated shootout creation failed: {e}")
            _debug_screenshot(page, "fatal_failure")
            raise

        finally:
            browser.close()


if __name__ == "__main__":
    main()
