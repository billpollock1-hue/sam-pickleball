#!/usr/bin/env python3
"""
patch_add_shootout_exists_guard.py

One-time patch: adds detection for DEN's "a shootout is already active for
this date" warning (appears after clicking the Create Shootout button when
one was already manually launched -- e.g. a human noticed an 8th player
sign up and launched it themselves before the automated poller's next
5-minute cycle). Without this, create_shootout.py would blindly proceed
past that warning and risk creating a duplicate/conflicting shootout.

Wording of DEN's actual warning hasn't been confirmed verbatim (not yet
seen live) -- checks a handful of plausible phrases rather than one exact
string, since guessing wrong would let a real warning slip through
undetected. Treated as a SUCCESSFUL outcome (clean exit, code 0), not an
error: launcher_poller.py's own success check is just "did the process
exit 0", so this correctly marks today as done and stops the retry loop
without needing any changes there.

Run once from the assignments/ directory:
    python3 patch_add_shootout_exists_guard.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "create_shootout.py"

OLD_PRE_CREATE = '''def create_shootout(page, num_courts):
    print(f"Creating shootout with {num_courts} court(s)...")'''

NEW_PRE_CREATE = '''class ShootoutAlreadyExistsError(Exception):
    """
    Raised when DEN reports a shootout already exists for today -- most
    likely a human manually launched one after enough players signed up,
    ahead of the automated poller's next cycle. This is a SUCCESSFUL
    outcome from the launcher's perspective (today's shootout exists,
    nothing more to do), not a failure -- main() catches this specifically
    and exits cleanly rather than treating it like a real error.
    """
    pass


# Not confirmed verbatim against DEN's live wording -- a deliberately
# loose set of plausible fragments rather than one exact string, so a
# close-but-not-identical real warning still gets caught.
ALREADY_EXISTS_PHRASES = [
    "already active",
    "already exists",
    "already been created",
    "delete the existing",
    "delete the current",
]


def _check_shootout_already_exists(page):
    """
    Best-effort check for DEN's already-active-shootout warning, run right
    after attempting to submit Create Shootout. Reads the whole page body
    rather than targeting a specific dialog element, since the exact
    element structure of that warning hasn't been observed live yet.
    """
    try:
        body_text = page.locator("body").inner_text().lower()
    except Exception:
        return False
    return any(phrase in body_text for phrase in ALREADY_EXISTS_PHRASES)


def create_shootout(page, num_courts):
    print(f"Creating shootout with {num_courts} court(s)...")'''

OLD_SUBMIT_CLICK = '''    page.get_by_role("button", name="Create Shootout", exact=True).click(timeout=5000)
    page.wait_for_timeout(1200)

    # "Sign-up sheet is still available for additional players" guard popup
    # -- ignore and proceed, per the documented routine.
    try:
        page.get_by_text("Yes", exact=True).click(timeout=3000)
        page.wait_for_timeout(800)
    except PWTimeout:
        pass  # popup didn't appear this time -- fine, nothing to dismiss'''

NEW_SUBMIT_CLICK = '''    page.get_by_role("button", name="Create Shootout", exact=True).click(timeout=5000)
    page.wait_for_timeout(1200)

    if _check_shootout_already_exists(page):
        raise ShootoutAlreadyExistsError(
            "DEN reports a shootout already exists for today -- most "
            "likely created manually after enough players signed up. "
            "Not creating a duplicate."
        )

    # "Sign-up sheet is still available for additional players" guard popup
    # -- ignore and proceed, per the documented routine.
    try:
        page.get_by_text("Yes", exact=True).click(timeout=3000)
        page.wait_for_timeout(800)
    except PWTimeout:
        pass  # popup didn't appear this time -- fine, nothing to dismiss'''

OLD_MAIN_EXCEPT = '''        except Exception as e:
            print(f"\\n✗ Automated shootout creation failed: {e}")
            _debug_screenshot(page, "fatal_failure")
            raise

        finally:
            browser.close()'''

NEW_MAIN_EXCEPT = '''        except ShootoutAlreadyExistsError as e:
            print(f"\\n✓ {e}")
            print(f"LAUNCH_RESULT: {json.dumps({'players_removed': [], 'already_existed': True})}")
            # Not re-raised -- exits cleanly (code 0) so launcher_poller.py
            # correctly treats today as done rather than retrying.

        except Exception as e:
            print(f"\\n✗ Automated shootout creation failed: {e}")
            _debug_screenshot(page, "fatal_failure")
            raise

        finally:
            browser.close()'''


def main():
    text = TARGET.read_text(encoding="utf-8")

    for old, new, label in [
        (OLD_PRE_CREATE, NEW_PRE_CREATE, "exception class + detection helper"),
        (OLD_SUBMIT_CLICK, NEW_SUBMIT_CLICK, "submit-click check"),
        (OLD_MAIN_EXCEPT, NEW_MAIN_EXCEPT, "main() except clause"),
    ]:
        count = text.count(old)
        if count != 1:
            print(f"✗ Aborting: expected exactly 1 match for {label}, found {count}. "
                  f"File may have already been patched, or changed unexpectedly.")
            return 1
        text = text.replace(old, new)

    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — added already-exists detection to create_shootout().")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
