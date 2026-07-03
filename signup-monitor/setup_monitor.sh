#!/bin/zsh
# One-time setup for the Pickleball Den signup monitor.
# Creates a runtime home in ~/Library/Application Support/PBMonitor/ so that
# the launchd agent (which cannot access ~/Documents) can run without issues.
#
# Run this once from Terminal, then run install_monitor.sh to activate the agent.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ASSIGNMENTS_DIR="$(cd "$SCRIPT_DIR/../assignments" && pwd)"
RUNTIME_DIR="$HOME/Library/Application Support/PBMonitor"
VENV="$RUNTIME_DIR/venv"
SESSION_SRC="$ASSIGNMENTS_DIR/den_session.json"

echo "Setting up monitor runtime in: $RUNTIME_DIR"
mkdir -p "$RUNTIME_DIR/logs"

# ── Create venv ─────────────────────────────────────────────────────────────
if [[ ! -d "$VENV" ]]; then
    echo "Creating Python venv..."
    python3 -m venv "$VENV"
fi

echo "Installing packages..."
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet playwright pandas openpyxl

echo "Installing Playwright browser (Chromium)..."
"$VENV/bin/playwright" install chromium

# ── Copy session file if available ──────────────────────────────────────────
if [[ -f "$SESSION_SRC" ]]; then
    echo "Copying session from assignments/..."
    cp "$SESSION_SRC" "$RUNTIME_DIR/den_session.json"
else
    echo "No session file found — browser will load fresh (you may need to log in on first run)."
fi

# ── Copy monitor script (updating paths) ────────────────────────────────────
echo "Copying monitor script..."
cp "$SCRIPT_DIR/monitor_signups.py" "$RUNTIME_DIR/monitor_signups.py"
cp "$SCRIPT_DIR/generate_signup_viewer.py" "$RUNTIME_DIR/generate_signup_viewer.py"

# Patch BASE_DIR and add session-sync in the copied script
python3 - "$RUNTIME_DIR/monitor_signups.py" "$ASSIGNMENTS_DIR" "$RUNTIME_DIR" << 'PYSCRIPT'
import sys, re

script_path, den_dir, runtime_dir = sys.argv[1], sys.argv[2], sys.argv[3]
with open(script_path) as f:
    src = f.read()

# Rewrite BASE_DIR to point to the runtime dir (Library)
src = re.sub(
    r"BASE_DIR = Path\(__file__\)\.parent",
    f'BASE_DIR = Path("{runtime_dir}")',
    src
)

# Add session-sync: after saving state, also sync session back to assignments/
sync_code = f'''
    # Sync session back to assignments/ so den_assignments.py stays in sync
    _den_session = Path("{den_dir}") / "den_session.json"
    try:
        import shutil
        shutil.copy2(str(SESSION_FILE), str(_den_session))
    except Exception:
        pass
'''

# Insert sync just before `save_state(state)` at the end of run_monitor
src = src.replace(
    "    state[\"snapshots\"] = snapshots\n    save_state(state)",
    "    state[\"snapshots\"] = snapshots\n    save_state(state)" + sync_code
)

with open(script_path, 'w') as f:
    f.write(src)
print("Script patched.")
PYSCRIPT

echo ""
echo "Setup complete."
echo "Runtime directory: $RUNTIME_DIR"
echo ""
echo "Next: run ./install_monitor.sh to activate the launchd agent."
