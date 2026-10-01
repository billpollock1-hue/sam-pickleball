from pathlib import Path
p = Path("assignments/create_shootout_rating_seeded.py")
s = p.read_text()
old = '''    page.get_by_role("button", name="Create Shootout", exact=True).click(timeout=60000)
    page.wait_for_timeout(1200)

    return actual_shuffle_mode

    # "Sign-up sheet is still available for additional players" guard popup
    # -- ignore and proceed, per the documented routine.
    try:
        page.get_by_text("Yes", exact=True).click(timeout=3000)
        page.wait_for_timeout(800)
    except PWTimeout:
        pass  # popup didn't appear this time -- fine, nothing to dismiss
'''
new = '''    page.get_by_role("button", name="Create Shootout", exact=True).click(timeout=60000)
    page.wait_for_timeout(1200)

    # "Sign-up sheet is still available for additional players" guard popup
    # -- ignore and proceed, per the documented routine. This block was
    # previously unreachable (it sat after the return), so the popup was
    # never dismissed. Fixed 2026-09-29 MST.
    try:
        page.get_by_text("Yes", exact=True).click(timeout=3000)
        page.wait_for_timeout(800)
    except PWTimeout:
        pass  # popup didn't appear this time -- fine, nothing to dismiss

    return actual_shuffle_mode
'''
n = s.count(old)
if n != 1:
    raise SystemExit(f"ABORT: expected 1 match, found {n} -- file has diverged, nothing changed")
p.write_text(s.replace(old, new))
print("PATCHED OK")
