#!/usr/bin/env python3
"""
patch_fix_duplicate_scrape_merge.py

One-time patch: ensure_model_current() had a real bug that duplicated 18
rows of real July 8, 2026 data into master_history_raw.csv during a live
test on 2026-08-21. Root cause: today_results.csv is a fixed, reused
filename that scrape.js writes to -- the merge code only checked whether
that file existed and had rows, never whether it was actually freshly
written by THIS run. A stale leftover file from an unrelated earlier
scrape got silently re-merged, even though this run's own scrape
genuinely found 0 results for its actual target window.

Two independent layers of fix:
  1. Delete today_results.csv before every scrape attempt, so a stale
     leftover from a prior run can never be silently reused.
  2. Deduplicate scraped rows against existing master CSV content
     (exact full-row match) before appending anything -- a second,
     independent safety net regardless of what upstream scraping does.

Run once from the assignments/ directory:
    python3 patch_fix_duplicate_scrape_merge.py
"""

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "den_assignments.py"

OLD_BLOCK = '''        scrape_script = MODEL_DIR / "scraper" / "scrape.js"
        today_csv = MODEL_DIR / "output" / "today_results.csv"
        today_str = today.strftime("%m%d%y")

        if scrape_script.exists():
            # scrape.js prompts for manual login/navigation via the terminal
            # (readline), so stdin/stdout must stay connected to this
            # terminal — capturing output would hide those prompts and the
            # process would hang until it times out with no way to respond.
            try:
                result = subprocess.run(
                    ["node", str(scrape_script), "--start", today_str, "--end", today_str,
                     "--output", str(today_csv)],
                    cwd=str(MODEL_DIR),
                )
                if result.returncode == 0 and today_csv.exists():
                    scraped = pd.read_csv(today_csv)
                    # Drop duplicate header rows safely
                    first_col = scraped.columns[0]
                    scraped = scraped[scraped[first_col] != first_col]
                    scraped = scraped.reset_index(drop=True)
                    if len(scraped) > 0:
                        scraped.to_csv(MODEL_INPUT, mode="a", header=False, index=False)
                        raw_latest = today
                        print(f"✓ Appended {len(scraped)} rows from today's scrape to master CSV.")
                    else:
                        print(f"⚠ Scrape ran but returned no rows for {today_str}. Results may not be posted yet.")
                else:
                    print(f"⚠ Scrape exited with code {result.returncode}. Results may not be posted yet.")
            except Exception as e:
                print(f"⚠ Scraping error: {e}")
        else:
            print(f"⚠ Scrape script not found: {scrape_script}")'''

NEW_BLOCK = '''        scrape_script = MODEL_DIR / "scraper" / "scrape.js"
        today_csv = MODEL_DIR / "output" / "today_results.csv"
        today_str = today.strftime("%m%d%y")

        # Delete any stale leftover from a prior, unrelated scrape run
        # before invoking scrape.js -- today_csv is a fixed, reused
        # filename. Without this, a leftover file from an earlier scrape
        # (e.g. a past backfill) could get silently re-merged even when
        # THIS run's own scrape genuinely finds nothing -- confirmed live
        # 2026-08-21, duplicated 18 rows of real July 8 data this way.
        if today_csv.exists():
            today_csv.unlink()

        if scrape_script.exists():
            # scrape.js prompts for manual login/navigation via the terminal
            # (readline), so stdin/stdout must stay connected to this
            # terminal — capturing output would hide those prompts and the
            # process would hang until it times out with no way to respond.
            try:
                result = subprocess.run(
                    ["node", str(scrape_script), "--start", today_str, "--end", today_str,
                     "--output", str(today_csv)],
                    cwd=str(MODEL_DIR),
                )
                if result.returncode == 0 and today_csv.exists():
                    scraped = pd.read_csv(today_csv)
                    # Drop duplicate header rows safely
                    first_col = scraped.columns[0]
                    scraped = scraped[scraped[first_col] != first_col]
                    scraped = scraped.reset_index(drop=True)

                    # Second, independent safety net: never append a row
                    # that's already an exact match for one already in the
                    # master CSV, regardless of how it got scraped again.
                    if len(scraped) > 0:
                        common_cols = [c for c in scraped.columns if c in raw.columns]
                        before = len(scraped)
                        merge_check = scraped.merge(
                            raw[common_cols], on=common_cols, how="left", indicator=True
                        )
                        scraped = scraped[merge_check["_merge"].values == "left_only"].reset_index(drop=True)
                        skipped = before - len(scraped)
                        if skipped:
                            print(f"  Skipped {skipped} row(s) already present in master CSV (exact duplicate).")

                    if len(scraped) > 0:
                        scraped.to_csv(MODEL_INPUT, mode="a", header=False, index=False)
                        raw_latest = today
                        print(f"✓ Appended {len(scraped)} rows from today's scrape to master CSV.")
                    else:
                        print(f"⚠ Scrape ran but returned no new rows for {today_str}. Results may not be posted yet.")
                else:
                    print(f"⚠ Scrape exited with code {result.returncode}. Results may not be posted yet.")
            except Exception as e:
                print(f"⚠ Scraping error: {e}")
        else:
            print(f"⚠ Scrape script not found: {scrape_script}")'''


def main():
    text = TARGET.read_text(encoding="utf-8")
    count = text.count(OLD_BLOCK)
    if count != 1:
        print(f"✗ Aborting: expected exactly 1 match, found {count}. "
              f"File may have already been patched, or changed unexpectedly.")
        return 1
    text = text.replace(OLD_BLOCK, NEW_BLOCK)
    TARGET.write_text(text, encoding="utf-8")
    print(f"✓ Patched {TARGET} — stale today_results.csv now deleted before "
          f"every scrape attempt, and scraped rows are deduplicated against "
          f"existing master CSV content before appending.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
