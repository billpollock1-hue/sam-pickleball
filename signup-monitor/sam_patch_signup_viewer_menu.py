#!/usr/bin/env python3
"""
patch_signup_viewer_menu_to_admin.py

One-time patch: the signup viewer's "<- Menu" link previously pointed to
index.html (the public SAM Pickleball menu). Since the Signup Sheet Logs
card itself was moved into the admin menu earlier, this back-link now
points there instead -- http://192.168.1.190:8765/, the admin server's
current LAN address (Wisconsin home network, confirmed 2026-08-16).

NOTE: this IP is only valid on this network. It WILL need updating at
each planned relocation handoff (iMac departs ~Aug 24-26, reunites with
Bill in Arizona ~Sept, MacBook takes over again ~Oct 9) -- see the
sam-pickleball-pipeline memory notes for the full relocation plan.

Also note this link will only actually connect from a device on the same
home network as the admin server -- signup_viewer.html itself is public
(served via GitHub Pages), so anyone off that network clicking Menu will
get a failed connection. Accepted tradeoff, matches the admin panel's
own no-password/LAN-only design.

Run once from the signup-monitor/ directory:
    python3 patch_signup_viewer_menu_to_admin.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "generate_signup_viewer.py"

OLD_LINE = '  <a href="index.html" class="back-btn">&larr; Menu</a>'
NEW_LINE = '  <a href="http://192.168.1.190:8765/" class="back-btn">&larr; Menu</a>'


def main():
    text = TARGET.read_text(encoding="utf-8")
    count = text.count(OLD_LINE)
    if count != 1:
        print(f"✗ Aborting: expected exactly 1 match, found {count}. "
              f"File may have already been patched, or changed unexpectedly.")
        return 1
    text = text.replace(OLD_LINE, NEW_LINE)
    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — Menu link now points to the admin panel "
          f"(http://192.168.1.190:8765/) instead of the public SAM menu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
