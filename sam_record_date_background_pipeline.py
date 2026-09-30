#!/usr/bin/env python3
"""
Patch: the "single shootout" branch of _handle_record_date replies as soon
as the date is saved to PARTIAL_SHOOTOUT_CSV; the scrape -> merge -> engine
rebuild -> refresh pipeline runs on a background thread. dates.html polls a
new GET /api/record-date-status for the result, same pattern as the
tryout-name fix (commit 02fd1ed7).

Why: real incident 2026-09-30 -- this path holds the HTTP request open
through the whole pipeline (scrape, merge, a 600s-timeout engine rebuild,
refresh). Bill saw "Load failed" even though the underlying work
eventually succeeded (once merge_csv.py's validation false positive was
also fixed, commit c95ff9d5). The long synchronous wait is a real,
separate contributor: any one of those steps taking a while leaves the
connection exposed to exactly this failure mode, independent of whether
the pipeline itself succeeds.

Reuses the existing _REBUILD_LOCK (added for the tryout-name fix) to
serialize against ANY background rebuild, not just this one -- both
pipelines write to the same /tmp/pickleball_model_latest.xlsx, so running
them concurrently would corrupt each other's temp file. Uses its own,
separate status dict so this page's progress doesn't cross-contaminate
the tryout-name page's.

Run once from the repo root: python3 sam_record_date_background_pipeline.py
Safe to re-run: asserts each anchor matches exactly once.
"""
from pathlib import Path

server_path = Path("launcher/launcher_server.py")
html_path = Path("launcher/dates.html")
server = server_path.read_text(encoding="utf-8")
html = html_path.read_text(encoding="utf-8")

if "_RECORD_DATE_STATE" in server or "pollRecordDateStatus" in html:
    print("Already applied -- nothing to do.")
    raise SystemExit(0)


def replace_once(text, old, new, label):
    n = text.count(old)
    assert n == 1, f"{label}: expected exactly 1 match, found {n}"
    return text.replace(old, new)


# ---------------------------------------------------------------- server ---

# 1. Shared state + background worker, right after the existing tryout
#    rebuild state block (reuses _REBUILD_LOCK, adds its own status dict).
anchor1 = 'def get_tryout_rebuild_status():'
assert server.count(anchor1) == 1, f"anchor1: expected exactly 1 match, found {server.count(anchor1)}"
insert_before = (
    '_RECORD_DATE_STATE_LOCK = threading.Lock()\n'
    '_RECORD_DATE_STATE = {"pending": 0, "state": "idle", "detail": ""}\n'
    '\n'
    '\n'
    'def get_record_date_status():\n'
    '    with _RECORD_DATE_STATE_LOCK:\n'
    '        if _RECORD_DATE_STATE["pending"] > 0:\n'
    '            return {"state": "running", "detail": ""}\n'
    '        return {"state": _RECORD_DATE_STATE["state"], "detail": _RECORD_DATE_STATE["detail"]}\n'
    '\n'
    '\n'
    'def _run_single_shootout_pipeline(date_str, refresh_fn):\n'
    '    """Background thread body for the \'single shootout\' record-date\n'
    '    path. Shares _REBUILD_LOCK with the tryout-name pipeline below --\n'
    '    both write to the same /tmp/pickleball_model_latest.xlsx, so they\n'
    '    must never run concurrently."""\n'
    '    result = ("failed", "pipeline did not run")\n'
    '    try:\n'
    '        with _REBUILD_LOCK:\n'
    '            try:\n'
    '                parsed = datetime.strptime(date_str, "%Y-%m-%d")\n'
    '                scrape_date = parsed.strftime("%m%d%y")\n'
    '                subprocess.run(\n'
    '                    ["node", "scraper/scrape.js", "--start", scrape_date, "--end", scrape_date,\n'
    '                     "--output", "data/latest_scrape.csv"],\n'
    '                    cwd=REPO_ROOT, check=True, timeout=120,\n'
    '                )\n'
    '                subprocess.run(\n'
    '                    ["python3", "scraper/merge_csv.py"],\n'
    '                    cwd=REPO_ROOT, check=True, timeout=60,\n'
    '                )\n'
    '                # /tmp-then-mv: writing large xlsx files directly into the\n'
    '                # Documents subtree has hit a real macOS write-timeout bug\n'
    '                # before -- always build there first.\n'
    '                subprocess.run(\n'
    '                    ["python3", "engine/pickleball_engine_v2.py",\n'
    '                     "--input", "data/master_history_raw.csv",\n'
    '                     "--output", "/tmp/pickleball_model_latest.xlsx"],\n'
    '                    cwd=REPO_ROOT, check=True, timeout=600,\n'
    '                )\n'
    '                subprocess.run(\n'
    '                    ["mv", "/tmp/pickleball_model_latest.xlsx",\n'
    '                     str(REPO_ROOT / "output/pickleball_model_latest.xlsx")],\n'
    '                    check=True,\n'
    '                )\n'
    '                refresh_fn()\n'
    '                result = ("ok", "scraped, merged, engine rebuilt, viewer refreshed")\n'
    '            except subprocess.CalledProcessError as e:\n'
    '                result = ("failed", f"pipeline step failed (exit {e.returncode}): {e}")\n'
    '            except subprocess.TimeoutExpired as e:\n'
    '                result = ("failed", f"pipeline step timed out: {e}")\n'
    '            except Exception as e:\n'
    '                result = ("failed", f"unexpected error: {e}")\n'
    '    finally:\n'
    '        with _RECORD_DATE_STATE_LOCK:\n'
    '            _RECORD_DATE_STATE["pending"] -= 1\n'
    '            _RECORD_DATE_STATE["state"], _RECORD_DATE_STATE["detail"] = result\n'
    '        print(f"single-shootout record-date pipeline: {result[0]} -- {result[1]}", flush=True)\n'
    '\n'
    '\n'
)
server = server.replace(anchor1, insert_before + anchor1)

# 2. Status route, right after the existing tryout-rebuild-status route.
route_anchor = (
    '        elif self.path == "/api/tryout-rebuild-status":\n'
    '            self._send_json(get_tryout_rebuild_status())\n'
)
assert server.count(route_anchor) == 1, f"route anchor: expected exactly 1 match, found {server.count(route_anchor)}"
server = server.replace(
    route_anchor,
    route_anchor + (
        '        elif self.path == "/api/record-date-status":\n'
        '            self._send_json(get_record_date_status())\n'
    ),
)

# 3. Replace the synchronous "single" branch body with a quick save + spawn.
old_single = (
    '        # date_type == "single"\n'
    '        if not self._append_csv_date(PARTIAL_SHOOTOUT_CSV, date_str):\n'
    '            self._send_json({"error": f"{date_str} is already recorded"}, status=409)\n'
    '            return\n'
    '        try:\n'
    '            parsed = datetime.strptime(date_str, "%Y-%m-%d")\n'
    '            scrape_date = parsed.strftime("%m%d%y")\n'
    '\n'
    '            subprocess.run(\n'
    '                ["node", "scraper/scrape.js", "--start", scrape_date, "--end", scrape_date,\n'
    '                 "--output", "data/latest_scrape.csv"],\n'
    '                cwd=REPO_ROOT, check=True, timeout=120,\n'
    '            )\n'
    '            subprocess.run(\n'
    '                ["python3", "scraper/merge_csv.py"],\n'
    '                cwd=REPO_ROOT, check=True, timeout=60,\n'
    '            )\n'
    '            # /tmp-then-mv: writing large xlsx files directly into the\n'
    '            # Documents subtree has hit a real macOS write-timeout bug\n'
    '            # before -- always build there first.\n'
    '            subprocess.run(\n'
    '                ["python3", "engine/pickleball_engine_v2.py",\n'
    '                 "--input", "data/master_history_raw.csv",\n'
    '                 "--output", "/tmp/pickleball_model_latest.xlsx"],\n'
    '                cwd=REPO_ROOT, check=True, timeout=600,\n'
    '            )\n'
    '            subprocess.run(\n'
    '                ["mv", "/tmp/pickleball_model_latest.xlsx",\n'
    '                 str(REPO_ROOT / "output/pickleball_model_latest.xlsx")],\n'
    '                check=True,\n'
    '            )\n'
    '            self._refresh_court_assignments_viewer()\n'
    '        except subprocess.CalledProcessError as e:\n'
    '            self._send_json({"error": f"Pipeline step failed (exit {e.returncode}): {e}"}, status=500)\n'
    '            return\n'
    '        except subprocess.TimeoutExpired as e:\n'
    '            self._send_json({"error": f"Pipeline step timed out: {e}"}, status=500)\n'
    '            return\n'
    '        self._send_json({\n'
    '            "date": date_str, "type": "single",\n'
    '            "status": "scraped, merged, engine rebuilt, viewer refreshed",\n'
    '        })\n'
)
new_single = (
    '        # date_type == "single"\n'
    '        # Reply as soon as the date is saved; the scrape/merge/rebuild/\n'
    '        # refresh pipeline runs in the background and this page polls\n'
    '        # /api/record-date-status for the outcome -- real incident\n'
    '        # 2026-09-30: this request used to stay open through the whole\n'
    '        # pipeline and "Load failed" in the browser even when the work\n'
    '        # eventually succeeded.\n'
    '        if not self._append_csv_date(PARTIAL_SHOOTOUT_CSV, date_str):\n'
    '            self._send_json({"error": f"{date_str} is already recorded"}, status=409)\n'
    '            return\n'
    '        with _RECORD_DATE_STATE_LOCK:\n'
    '            _RECORD_DATE_STATE["pending"] += 1\n'
    '        try:\n'
    '            threading.Thread(\n'
    '                target=_run_single_shootout_pipeline,\n'
    '                args=(date_str, self._refresh_court_assignments_viewer),\n'
    '                daemon=True,\n'
    '            ).start()\n'
    '        except Exception as e:\n'
    '            with _RECORD_DATE_STATE_LOCK:\n'
    '                _RECORD_DATE_STATE["pending"] -= 1\n'
    '            self._send_json(\n'
    '                {"error": f"Recorded, but could not start the pipeline: {e}"},\n'
    '                status=500)\n'
    '            return\n'
    '        self._send_json({\n'
    '            "date": date_str, "type": "single",\n'
    '            "status": "saved; scrape/merge/rebuild pipeline started in the background",\n'
    '        }, status=202)\n'
)
n = server.count(old_single)
assert n == 1, f"single-branch anchor: expected exactly 1 match, found {n}"
server = server.replace(old_single, new_single)

# ------------------------------------------------------------------ page ---

html = replace_once(
    html,
    "'Scraping, merging, and rebuilding — this may take a couple minutes...'",
    "'Saving...'",
    "pending text",
)
old_ok = (
    "      statusEl.className = 'ok';\n"
    "      statusEl.textContent = `Done: ${date} recorded as \"${type === 'none' ? 'no shootout' : 'single shootout'}\" — ${data.status}.`;\n"
    "      loadRecordedDates();"
)
new_ok = (
    "      if (type === 'single') {\n"
    "        statusEl.className = 'pending';\n"
    "        statusEl.textContent = `Saved: ${date} recorded as \"single shootout\". Scraping, merging, and rebuilding in the background — this message updates when it finishes (a few minutes)...`;\n"
    "        loadRecordedDates();\n"
    "        pollRecordDateStatus(date);\n"
    "      } else {\n"
    "        statusEl.className = 'ok';\n"
    "        statusEl.textContent = `Done: ${date} recorded as \"no shootout\" — ${data.status}.`;\n"
    "        loadRecordedDates();\n"
    "      }"
)
html = replace_once(html, old_ok, new_ok, "success branch")

poll_fn = '''
async function pollRecordDateStatus(date) {
  const statusEl = document.getElementById('status');
  const started = Date.now();
  const MAX_MS = 15 * 60 * 1000;
  while (Date.now() - started < MAX_MS) {
    await new Promise(r => setTimeout(r, 5000));
    try {
      const resp = await fetch('/api/record-date-status');
      const s = await resp.json();
      if (s.state === 'ok') {
        statusEl.className = 'ok';
        statusEl.textContent = `Done: ${date} recorded as "single shootout" — ${s.detail}.`;
        return;
      }
      if (s.state === 'failed') {
        statusEl.className = 'err';
        statusEl.textContent = `Saved, but the pipeline failed: ${s.detail}. The date is recorded; the data may not be fully merged yet.`;
        return;
      }
      if (s.state === 'idle') {
        statusEl.className = 'err';
        statusEl.textContent = 'Saved, but the server has no record of a pipeline running (it may have restarted). The date is recorded; check back in a few minutes.';
        return;
      }
      // state === 'running': keep waiting
    } catch (e) {
      // transient error while polling: keep trying until the time limit
    }
  }
  statusEl.className = 'err';
  statusEl.textContent = 'Saved, but the pipeline is taking longer than 15 minutes. The date is recorded; check back later.';
}
'''
html = replace_once(html, "loadRecordedDates();\n</script>", "loadRecordedDates();\n" + poll_fn + "</script>", "script close")

server_path.write_text(server, encoding="utf-8")
html_path.write_text(html, encoding="utf-8")
print("launcher_server.py and dates.html updated successfully")
