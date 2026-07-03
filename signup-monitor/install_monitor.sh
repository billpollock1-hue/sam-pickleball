#!/bin/zsh
# Install or uninstall the Pickleball Den signup monitor as a macOS launchd agent.
# Requires setup_monitor.sh to have been run first.
#
# Usage:
#   ./install_monitor.sh           — install and start
#   ./install_monitor.sh uninstall — stop and remove

LABEL="com.pickleballden.signup-monitor"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
RUNTIME_DIR="$HOME/Library/Application Support/PBMonitor"
VENV="$RUNTIME_DIR/venv"
SCRIPT="$RUNTIME_DIR/monitor_signups.py"
LOG_OUT="$RUNTIME_DIR/logs/monitor_stdout.log"
LOG_ERR="$RUNTIME_DIR/logs/monitor_stderr.log"

if [[ "$1" == "uninstall" ]]; then
    echo "Stopping and removing signup monitor..."
    launchctl unload "$PLIST" 2>/dev/null
    rm -f "$PLIST"
    echo "Done. Monitor removed."
    exit 0
fi

if [[ ! -d "$RUNTIME_DIR" || ! -f "$SCRIPT" ]]; then
    echo "Error: runtime directory not set up."
    echo "Run ./setup_monitor.sh first, then re-run this script."
    exit 1
fi

mkdir -p "$RUNTIME_DIR/logs"

# Write the plist — uses Library venv Python directly (no Documents access needed)
cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>

    <key>ProgramArguments</key>
    <array>
        <string>$VENV/bin/python3</string>
        <string>$SCRIPT</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$RUNTIME_DIR</string>

    <key>StartInterval</key>
    <integer>900</integer>

    <key>StandardOutPath</key>
    <string>$LOG_OUT</string>

    <key>StandardErrorPath</key>
    <string>$LOG_ERR</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>HOME</key>
        <string>$HOME</string>
        <key>PLAYWRIGHT_BROWSERS_PATH</key>
        <string>$HOME/Library/Caches/ms-playwright</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
PLIST_EOF

# Unload any existing version first
launchctl unload "$PLIST" 2>/dev/null

# Load and start
launchctl load "$PLIST"

echo "Monitor installed and started."
echo "Runs every 15 minutes."
echo "Logs:    $RUNTIME_DIR/logs/"
echo "Script:  $SCRIPT  (edit here after setup, then re-run setup_monitor.sh to sync)"
echo ""
echo "To check status:   launchctl list | grep pickleballden"
echo "To view output:    tail -f \"$LOG_OUT\""
echo "To uninstall:      $(cd "$(dirname "$0")" && pwd)/install_monitor.sh uninstall"
