#!/bin/bash
cd "$(dirname "$0")"

echo ""
echo "=== Pickleball Model — Full Update ==="
bash run_all.sh

echo ""
echo "Run 'Open Charts.command' to view the HTML charts."
open output/pickleball_model_latest.xlsx
