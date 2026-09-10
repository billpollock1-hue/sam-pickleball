"""
Patch: switch build_rating_gap_distribution()'s margin buckets from the
asymmetric 5-bucket scheme (1-2, 3-4, 5-6, 7-8, 9-11) to a symmetric
4-bucket scheme (1-3, 4-6, 7-8, 9-11) -- close and blowout now each span
3 of pickleball's 11 possible margin values, matching the definition
already used elsewhere in the storybook (% Decided by <=3 / 9+).

Usage:
    cd "/Users/billpollock/Documents/SAM Pickleball/sam-pickleball/engine"
    python3 patch_gap_distribution_buckets.py
"""
from pathlib import Path

FILE_PATH = Path("pickleball_engine_v2.py")

OLD = '''    diff_bins   = [0, 2, 4, 6, 8, float("inf")]
    diff_labels = ["1–2", "3–4", "5–6", "7–8", "9–11"]'''

NEW = '''    diff_bins   = [0, 3, 6, 8, float("inf")]
    diff_labels = ["1–3", "4–6", "7–8", "9–11"]'''

content = FILE_PATH.read_text(encoding="utf-8")

if OLD not in content:
    print("PATTERN NOT FOUND -- file may have already changed since this patch was written.")
    print("No changes made. Paste back the current diff_bins/diff_labels lines so I can rewrite this patch.")
else:
    content = content.replace(OLD, NEW)
    FILE_PATH.write_text(content, encoding="utf-8")
    print("Patched successfully: diff_bins/diff_labels now use the symmetric 1-3/4-6/7-8/9-11 scheme.")
