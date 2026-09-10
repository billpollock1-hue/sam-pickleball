#!/usr/bin/env python3
"""
patch_dismiss_on_success_too.py

One-time patch: confirmed live 2026-08-25 that Vaadin's Move Players
dropdown overlay can remain visually open (intercepting clicks) even
after a SUCCESSFUL option selection, not just after a failed one. The
existing Escape-dismiss only ran in the except block, so it never had
a reason to fire when the click itself reported success -- leaving the
very next click ("Create Shootout") to crash on the same stuck-overlay
symptom the except-block dismiss was originally built for.

Adds the same Escape-dismiss unconditionally right after a successful
selection too, wrapped in its own try/except so it can never itself
throw.

Run once from the assignments/ directory:
    python3 patch_dismiss_on_success_too.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "create_shootout_rating_seeded.py"

OLD_BLOCK = '''        page.get_by_role("option", name=target_text, exact=True).click(timeout=3000)
        page.wait_for_timeout(500)
    except Exception as e:'''

NEW_BLOCK = '''        page.get_by_role("option", name=target_text, exact=True).click(timeout=3000)
        page.wait_for_timeout(500)
        # Proactively dismiss the dropdown overlay even on a SUCCESSFUL
        # click -- confirmed live 2026-08-25 that Vaadin's overlay can
        # remain visually open/intercepting clicks briefly after a
        # successful selection, not just after a failed one, blocking
        # the very next click ("Create Shootout") with the same
        # stuck-overlay symptom the except-block dismiss below was
        # originally built for.
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        except Exception:
            pass
    except Exception as e:'''


def main():
    text = TARGET.read_text(encoding="utf-8")
    count = text.count(OLD_BLOCK)
    if count != 1:
        print(f"✗ Aborting: expected exactly 1 match, found {count}. "
              f"File may have already been patched, or changed unexpectedly.")
        return 1
    text = text.replace(OLD_BLOCK, NEW_BLOCK)
    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — dropdown overlay now dismissed proactively "
          f"even after a successful Move Players selection.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
