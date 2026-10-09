#!/bin/zsh
# Run this to trace where the court assignments viewer's "Rating" column comes from.
# Paste the full output back to Claude.

cd ~/Documents/"SAM Pickleball"/sam-pickleball/assignments/ || exit 1

echo "=== 1. Does den_assignments.py read pickleball_model_latest.xlsx directly, or full_player_log? ==="
grep -n "MODEL_OUTPUT\|pickleball_model_latest\|full_player_log\|player_log\|nhd_pre_rating\|nhd_post_rating" den_assignments.py

echo ""
echo "=== 2. Same check in generate_assignments_viewer.py ==="
grep -n "MODEL_OUTPUT\|pickleball_model_latest\|full_player_log\|player_log\|nhd_pre_rating\|nhd_post_rating\|Rating" generate_assignments_viewer.py

echo ""
echo "=== 3. Which sheet/column of the xlsx actually gets read for the 'Rating' column ==="
grep -n "read_excel\|sheet_name\|\.xlsx" den_assignments.py generate_assignments_viewer.py
