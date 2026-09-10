#!/usr/bin/env python3
"""
patch_dismiss_stuck_dropdown.py

One-time patch: fixes a real bug found in live testing (2026-08-22). If
clicking the Move Players dropdown option fails, the dropdown's overlay
can be left stuck open, invisibly covering the whole page and blocking
every subsequent click -- including "Create Shootout" itself, crashing
the entire launch. The fail-soft design only ever intended a failed
Move Players attempt to leave Den's existing value untouched and
continue; it was never supposed to be able to break anything downstream.

Adds an explicit Escape-key dismiss in the failure path, wrapped in its
own try/except so it can never itself throw and break the fail-soft
guarantee, even if there's nothing actually open to dismiss.

Run once from the assignments/ directory:
    python3 patch_dismiss_stuck_dropdown.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "create_shootout.py"

OLD_BLOCK = '''    except Exception as e:
        print(f"  \\u26a0 Could not set Move Players field: {e} -- leaving Den's "
              f"existing value untouched rather than failing the whole launch.")'''

NEW_BLOCK = '''    except Exception as e:
        print(f"  \\u26a0 Could not set Move Players field: {e} -- leaving Den's "
              f"existing value untouched rather than failing the whole launch.")
        # A failed click can leave the dropdown's overlay stuck open,
        # invisibly blocking every subsequent click on the page --
        # including "Create Shootout" itself, crashing the whole launch.
        # Confirmed live 2026-08-22. Explicitly dismiss it so a Move
        # Players failure can never take down anything downstream.
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        except Exception:
            pass'''


def main():
    text = TARGET.read_text(encoding="utf-8")
    count = text.count(OLD_BLOCK)
    if count != 1:
        print(f"✗ Aborting: expected exactly 1 match, found {count}. "
              f"File may have already been patched, or changed unexpectedly.")
        return 1
    text = text.replace(OLD_BLOCK, NEW_BLOCK)
    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — a failed Move Players click now dismisses "
          f"any stuck-open dropdown overlay before continuing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
