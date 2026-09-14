#!/usr/bin/env python3
"""
patch_add_move_players_field.py

One-time patch: sets DEN's "Move Players" field on the Create Shootout
form to match launcher_config.json's shuffle_mode ("2u2b" -> "Two-up /
Two-down", "1u1b2s" -> "One-up / One-down"). Field text confirmed via a
live screenshot (no "2 Stay" option, contrary to earlier assumptions
elsewhere in the codebase).

NOT YET LIVE-TESTED against the real page -- built from a screenshot
alone. Every other DEN field interaction in this codebase needed at
least one round of live debugging to get exactly right (Search button,
View Players link, removal dialog); this is deliberately fail-soft --
if the selector doesn't match, it logs a warning and leaves Den's
existing value untouched rather than aborting the whole launch over a
non-critical field.

Run once from the assignments/ directory:
    python3 patch_add_move_players_field.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "create_shootout.py"

OLD_IMPORTS_AREA = '''def create_shootout(page, num_courts):
    print(f"Creating shootout with {num_courts} court(s)...")'''

NEW_IMPORTS_AREA = '''# Absolute path -- same reasoning as other cross-script coordination
# files in this codebase (e.g. the auto-removal marker): this script
# always runs from assignments/, but the launcher config always lives
# in launcher/, regardless of which copy of this script is running.
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
    any error, logs a warning and leaves Den's existing value untouched
    rather than aborting the whole shootout creation over this one
    non-critical field.
    """
    target_text = "Two-up / Two-down" if shuffle_mode == "2u2b" else "One-up / One-down"
    print(f"  Setting Move Players to: {target_text}")
    try:
        move_players_label = page.get_by_text("Move Players", exact=False)
        move_players_field = move_players_label.locator(
            "xpath=following::*[self::vaadin-select or self::div][1]"
        )
        move_players_field.click(timeout=3000)
        page.wait_for_timeout(500)
        page.get_by_text(target_text, exact=True).click(timeout=3000)
        page.wait_for_timeout(500)
    except Exception as e:
        print(f"  \\u26a0 Could not set Move Players field: {e} -- leaving Den's "
              f"existing value untouched rather than failing the whole launch.")
        _debug_screenshot(page, "move_players_field")


def create_shootout(page, num_courts):
    print(f"Creating shootout with {num_courts} court(s)...")'''

OLD_AFTER_COURTS = '''    except Exception as e:
        _debug_screenshot(page, "create_shootout_courts_field")
        raise RuntimeError(f"Could not set Number of Courts field: {e}")

    # Same ambiguity pattern as the earlier "Search" button fix'''

NEW_AFTER_COURTS = '''    except Exception as e:
        _debug_screenshot(page, "create_shootout_courts_field")
        raise RuntimeError(f"Could not set Number of Courts field: {e}")

    set_move_players(page, load_shuffle_mode())

    # Same ambiguity pattern as the earlier "Search" button fix'''


def main():
    text = TARGET.read_text(encoding="utf-8")

    for old, new, label in [
        (OLD_IMPORTS_AREA, NEW_IMPORTS_AREA, "helper functions"),
        (OLD_AFTER_COURTS, NEW_AFTER_COURTS, "call site after Number of Courts"),
    ]:
        count = text.count(old)
        if count != 1:
            print(f"✗ Aborting: expected exactly 1 match for {label}, found {count}. "
                  f"File may have already been patched, or changed unexpectedly.")
            return 1
        text = text.replace(old, new)

    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — Move Players field now set from "
          f"launcher_config.json's shuffle_mode (fail-soft, not yet live-tested).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
