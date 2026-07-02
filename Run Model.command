#!/bin/bash
cd "$(dirname "$0")"

echo ""
echo "=== Pickleball Model — Full Update ==="
bash run_all.sh

echo ""
echo "Run 'Open Charts.command' to view the HTML charts."
open output/pickleball_model_latest.xlsx

echo ""
echo "Pushing updated session viewer to GitHub Pages..."
git add docs/
git diff --cached --quiet && echo "No changes to publish." || (
  git commit -m "Update session viewer and charts $(date '+%Y-%m-%d')" &&
  git push &&
  echo "Published: https://billpollock1-hue.github.io/sam-pickleball/session_viewer.html"
)
