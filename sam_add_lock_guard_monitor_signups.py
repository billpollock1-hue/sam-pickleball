#!/usr/bin/env python3
"""
One-off patch: adds stale .git/index.lock self-healing to
signup-monitor/monitor_signups.py's sync_signup_viewer_to_live_site(),
matching the guard already added to run_all.sh (commit e17927c5) and
assignments/refresh_assignments.py.

Real incident 2026-09-21: a stale index.lock (from a crashed git
process) silently blocked every git publish for 5.5+ hours. This is
the third of three independent git-committing entry points in this
codebase (run_all.sh, refresh_assignments.py, this one) -- all three
needed the same fix, since a lock left by any one of them can block
the others too.

Run once from the repo root: python3 sam_add_lock_guard_monitor_signups.py
Safe to re-run: asserts the anchor matches exactly once.
"""
from pathlib import Path

path = Path("signup-monitor/monitor_signups.py")
content = path.read_text()

anchor = (
    '        status = subprocess.run(\n'
    '            ["git", "status", "--porcelain", "docs/signup_viewer.html"],\n'
    '            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30,\n'
    '        )'
)
assert content.count(anchor) == 1, f"anchor matches: {content.count(anchor)}"

new = (
    '        # Same self-healing check as run_all.sh\'s guard -- a crashed git\n'
    '        # process can leave .git/index.lock behind, silently blocking\n'
    '        # every future git operation here too (real incident 2026-09-21:\n'
    '        # blocked 5.5+ hours of publishing with no visible failure).\n'
    '        # Only removed if nothing currently has it open.\n'
    '        lock_path = REPO_ROOT / ".git" / "index.lock"\n'
    '        if lock_path.exists():\n'
    '            check = subprocess.run(["lsof", str(lock_path)], capture_output=True, timeout=10)\n'
    '            if check.returncode != 0:\n'
    '                print(f"[{timestamp_str}]   ⚠ Found stale {lock_path} with nothing holding it open -- removing.")\n'
    '                lock_path.unlink()\n'
    '            else:\n'
    '                print(f"[{timestamp_str}]   ⚠ Found {lock_path} and something has it open -- skipping this publish.")\n'
    '                return\n'
    '\n'
    + anchor
)
content = content.replace(anchor, new)

path.write_text(content)
print("monitor_signups.py updated successfully")
