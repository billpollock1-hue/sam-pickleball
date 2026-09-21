#!/bin/zsh
cd "$HOME/Documents/SAM Pickleball/sam-pickleball/assignments/scripts"
"$HOME/Documents/SAM Pickleball/sam-pickleball/.venv/bin/python3" fc_tracker.py

echo
echo "Done. You can close this window."
read -n 1 -s -r "?Press any key to close..."
