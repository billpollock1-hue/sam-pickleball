#!/usr/bin/env python3
"""
patch_port_move_players_to_rating_seeded.py

One-time patch: create_shootout_rating_seeded.py -- the script that
actually runs in production (launcher_config.json's mode is
"elo_autolaunch") -- had NONE of the Move Players automation built into
create_shootout.py on 2026-08-22. This fully explains 2026-08-24's real
observation (Two-up/Two-down used despite "One-up / One-down" being
configured): the code to even attempt changing it never existed here.

Ports the whole feature over, using the working selector and
dropdown-dismiss fix already proven in create_shootout.py, PLUS a new
read-back verification step: set_move_players() now returns the field's
ACTUAL value read back from the page after the attempt (success or
failure), rather than callers just logging what was merely requested.
That return value flows through create_shootout()'s own return, the
call site, and into this script's own LAUNCH_RESULT as
shootout2_shuffle_mode -- so the log finally reflects reality.

Run once from the assignments/ directory:
    python3 patch_port_move_players_to_rating_seeded.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "create_shootout_rating_seeded.py"

OLD_FUNC_START = '''def create_shootout(page, num_courts):
    print(f"Creating shootout with {num_courts} court(s)...")'''

NEW_FUNC_START = '''# Absolute path -- same reasoning as other cross-script coordination
# files in this codebase: this script always runs from assignments/, but
# the launcher config always lives in launcher/, regardless of which
# copy of this script is running.
LAUNCHER_CONFIG_PATH = Path(
    "/Users/billpollock/Documents/SAM Pickleball/sam-pickleball/launcher/launcher_config.json"
)


def load_shuffle_mode():
    """
    Reads shuffle_mode from launcher_config.json ("2u2b" or "1u1b2s").
    Defaults to "2u2b" (Den's own default) if the file is missing,
    unreadable, or the field isn't set -- never blocks a launch over
    this.
    """
    try:
        cfg = json.loads(LAUNCHER_CONFIG_PATH.read_text())
        mode = cfg.get("shuffle_mode", "2u2b")
        return mode if mode in ("2u2b", "1u1b2s") else "2u2b"
    except Exception:
        return "2u2b"


def set_move_players(page, shuffle_mode):
    """
    Sets the "Move Players" field to match shuffle_mode. Fail-soft: on
    any error, logs a warning, dismisses any stuck-open dropdown overlay
    (a failed click can otherwise block every subsequent click on the
    page, including "Create Shootout" itself -- confirmed live
    2026-08-22), and leaves Den's existing value untouched rather than
    failing the whole shootout creation over this one non-critical
    field.

    Returns the field's ACTUAL current value, read back from the page
    after the attempt -- regardless of whether that attempt succeeded --
    so the caller can log what Den genuinely has set, not just what was
    requested.
    """
    target_text = "Two-up / Two-down" if shuffle_mode == "2u2b" else "One-up / One-down"
    print(f"  Setting Move Players to: {target_text}")
    move_players_field = None
    try:
        move_players_label = page.get_by_text("Move Players", exact=False)
        move_players_field = move_players_label.locator(
            "xpath=following::vaadin-select[1]"
        )
        move_players_field.click(timeout=3000)
        page.wait_for_timeout(500)
        page.get_by_text(target_text, exact=True).click(timeout=3000)
        page.wait_for_timeout(500)
    except Exception as e:
        print(f"  \\u26a0 Could not set Move Players field: {e} -- leaving Den's "
              f"existing value untouched rather than failing the whole launch.")
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        except Exception:
            pass
        _debug_screenshot(page, "move_players_field")

    try:
        if move_players_field is None:
            move_players_label = page.get_by_text("Move Players", exact=False)
            move_players_field = move_players_label.locator(
                "xpath=following::vaadin-select[1]"
            )
        actual_value = move_players_field.inner_text(timeout=2000).strip()
        return actual_value if actual_value else "Unknown"
    except Exception:
        return "Unknown"


def create_shootout(page, num_courts):
    print(f"Creating shootout with {num_courts} court(s)...")'''

OLD_AFTER_COURTS = '''    except Exception as e:
        _debug_screenshot(page, "create_shootout_courts_field")
        raise RuntimeError(f"Could not set Number of Courts field: {e}")

    # Same ambiguity pattern as the earlier "Search" button fix -- the
    # page has both an <h2>Create Shootout</h2> heading and the actual
    # submit button, and exact=False matches case-insensitively, so both
    # matched. get_by_role targets the button specifically.
    page.get_by_role("button", name="Create Shootout", exact=True).click(timeout=5000)
    page.wait_for_timeout(1200)'''

NEW_AFTER_COURTS = '''    except Exception as e:
        _debug_screenshot(page, "create_shootout_courts_field")
        raise RuntimeError(f"Could not set Number of Courts field: {e}")

    actual_shuffle_mode = set_move_players(page, load_shuffle_mode())

    # Same ambiguity pattern as the earlier "Search" button fix -- the
    # page has both an <h2>Create Shootout</h2> heading and the actual
    # submit button, and exact=False matches case-insensitively, so both
    # matched. get_by_role targets the button specifically.
    page.get_by_role("button", name="Create Shootout", exact=True).click(timeout=5000)
    page.wait_for_timeout(1200)

    return actual_shuffle_mode'''

OLD_CALL_SITE = '''            create_shootout(page, num_courts)
            check_in_all(page)'''

NEW_CALL_SITE = '''            actual_shuffle_mode = create_shootout(page, num_courts)
            check_in_all(page)'''

OLD_RESULT = '''            print(f"LAUNCH_RESULT: {json.dumps({'players_removed': excess_names, 'court_assignments': court_assignments_log})}")'''

NEW_RESULT = '''            print(f"LAUNCH_RESULT: {json.dumps({'players_removed': excess_names, 'court_assignments': court_assignments_log, 'shootout2_shuffle_mode': actual_shuffle_mode})}")'''


def main():
    text = TARGET.read_text(encoding="utf-8")

    for old, new, label in [
        (OLD_FUNC_START, NEW_FUNC_START, "new helper functions"),
        (OLD_AFTER_COURTS, NEW_AFTER_COURTS, "call site + return, inside create_shootout()"),
        (OLD_CALL_SITE, NEW_CALL_SITE, "capture return value at call site"),
        (OLD_RESULT, NEW_RESULT, "LAUNCH_RESULT line"),
    ]:
        count = text.count(old)
        if count != 1:
            print(f"✗ Aborting: expected exactly 1 match for {label}, found {count}. "
                  f"File may have already been patched, or changed unexpectedly.")
            return 1
        text = text.replace(old, new)

    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — Move Players automation ported in, with "
          f"read-back verification so the log reflects Den's actual value.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
