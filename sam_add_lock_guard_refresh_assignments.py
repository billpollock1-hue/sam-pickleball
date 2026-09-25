#!/usr/bin/env python3
"""
One-off patch: adds stale .git/index.lock self-healing to
assignments/refresh_assignments.py's sync_to_live_site(), matching the
guard already added to run_all.sh (commit e17927c5).

Real incident 2026-09-21: a stale index.lock (from a crashed git
process) silently blocked every git publish for 5.5+ hours. run_all.sh
now self-heals; this closes the same gap in refresh_assignments.py,
which does its own independent git add/commit/push (called directly
by launcher_server.py's admin endpoints, not just via run_all.sh).

Run once from the repo root: python3 sam_add_lock_guard_refresh_assignments.py
Safe to re-run: asserts the anchor matches exactly once.
"""
from pathlib import Path

path = Path("assignments/refresh_assignments.py")
content = path.read_text()

anchor = (
    '        status = subprocess.run(\n'
    '            ["git", "status", "--porcelain", "docs/court_assignments.html"],\n'
    '            cwd=str(repo_root), capture_output=True, text=True, timeout=30,\n'
    '        )'
)
assert content.count(anchor) == 1, f"anchor matches: {content.count(anchor)}"

new = (
    '        # Same self-healing check as run_all.sh\'s guard -- a crashed git\n'
    '        # process can leave .git/index.lock behind, silently blocking\n'
    '        # every future git operation here too (real incident 2026-09-21:\n'
    '        # blocked 5.5+ hours of publishing with no visible failure).\n'
    '        # Only removed if nothing currently has it open.\n'
    '        lock_path = repo_root / ".git" / "index.lock"\n'
    '        if lock_path.exists():\n'
    '            check = subprocess.run(["lsof", str(lock_path)], capture_output=True, timeout=10)\n'
    '            if check.returncode != 0:\n'
    '                print(f"  ⚠ Found stale {lock_path} with nothing holding it open -- removing.")\n'
    '                lock_path.unlink()\n'
    '            else:\n'
    '                print(f"  ⚠ Found {lock_path} and something has it open -- skipping this publish.")\n'
    '                return\n'
    '\n'
    + anchor
)
content = content.replace(anchor, new)

path.write_text(content)
print("refresh_assignments.py updated successfully")
