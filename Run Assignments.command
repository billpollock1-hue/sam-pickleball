#!/bin/zsh
cd "$(dirname "$0")/assignments"
../.venv/bin/python3 den_assignments.py

echo
echo "Done. You can close this window."
read -n 1 -s -r "?Press any key to close..."
