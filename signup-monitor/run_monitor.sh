#!/bin/zsh
# Manually trigger one monitor pass using the deployed runtime copy
# (the same code the launchd agent runs every 15 minutes).
RUNTIME="$HOME/Library/Application Support/PBMonitor"
PYTHON="$RUNTIME/venv/bin/python3"
SCRIPT="$RUNTIME/monitor_signups.py"
STDOUT="$RUNTIME/logs/monitor_stdout.log"
STDERR="$RUNTIME/logs/monitor_stderr.log"
cd "$RUNTIME" && "$PYTHON" "$SCRIPT" >> "$STDOUT" 2>> "$STDERR"
