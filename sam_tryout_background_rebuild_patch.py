#!/usr/bin/env python3
"""
Patch: /api/record-tryout-name replies right after the name is saved; the
engine rebuild + court-assignments refresh run on a background thread; the
Identify Tryout Player page polls /api/tryout-rebuild-status for the result.

Why: the handler used to hold the HTTP request open through the whole rebuild
(minutes). On 2026-09-28 Safari showed "Network error: TypeError: Load failed"
even though the name had been saved and applied. The cause of that error was
not confirmed; replying immediately removes the long wait.

Behavior kept: validation, the 409 for an already-recorded date, the CSV
append, the engine/mv/refresh commands and their 600s timeout.
Behavior added: rebuilds are serialized by a lock (they share one /tmp
output file); the page still shows a success or a failure, via polling.
Not changed: no exclusion against the scheduled run_all.sh.

Run once from the repo root:  python3 sam_tryout_background_rebuild_patch.py
Safe to re-run: it stops if already applied, and every anchor must match once.
"""
from pathlib import Path

server_path = Path("launcher/launcher_server.py")
html_path = Path("launcher/tryout_name.html")
server = server_path.read_text(encoding="utf-8")
html = html_path.read_text(encoding="utf-8")

if "_run_tryout_rebuild" in server or "pollRebuildStatus" in html:
    print("Already applied -- nothing to do.")
    raise SystemExit(0)


def replace_once(text, old, new, label):
    n = text.count(old)
    assert n == 1, f"{label}: expected exactly 1 match, found {n}"
    return text.replace(old, new)


# ---------------------------------------------------------------- server ---

# 1. threading import
server = replace_once(
    server,
    "import socket\nimport subprocess\n",
    "import socket\nimport subprocess\nimport threading\n",
    "import threading",
)

# 2. shared state + background worker, right after the CSV path constant
csv_line = 'TRYOUT_NAME_FIXES_CSV = REPO_ROOT / "data" / "tryout_name_fixes.csv"\n'
state_block = csv_line + '''
# --- Background rebuild after recording a tryout name --------------------
# The rebuild takes minutes, so the request handler replies as soon as the
# name is saved and this worker does the rest. _REBUILD_LOCK serializes
# rebuilds (they all write /tmp/pickleball_model_latest.xlsx), so a queued
# rebuild always sees every row saved before it starts. "pending" counts
# queued + running rebuilds; the status endpoint reports "running" while it
# is above zero, then the result of the last one to finish.
_REBUILD_LOCK = threading.Lock()
_REBUILD_STATE_LOCK = threading.Lock()
_REBUILD_STATE = {"pending": 0, "state": "idle", "detail": ""}


def get_tryout_rebuild_status():
    with _REBUILD_STATE_LOCK:
        if _REBUILD_STATE["pending"] > 0:
            return {"state": "running", "detail": ""}
        return {"state": _REBUILD_STATE["state"], "detail": _REBUILD_STATE["detail"]}


def _run_tryout_rebuild(refresh_fn):
    """Background thread body. The name is already saved when this runs."""
    result = ("failed", "rebuild did not run")
    try:
        with _REBUILD_LOCK:
            try:
                # Re-run the engine so MANUAL_NAME_FIXES picks up the new entry
                # for any games already scraped under this date -- a harmless
                # no-op if the date has no games yet (a future signup sheet).
                # /tmp-then-mv: writing large xlsx files directly into the
                # Documents subtree has hit a real macOS write-timeout bug
                # before -- always build there first.
                subprocess.run(
                    ["python3", "engine/pickleball_engine_v2.py",
                     "--input", "data/master_history_raw.csv",
                     "--output", "/tmp/pickleball_model_latest.xlsx"],
                    cwd=REPO_ROOT, check=True, timeout=600,
                )
                subprocess.run(
                    ["mv", "/tmp/pickleball_model_latest.xlsx",
                     str(REPO_ROOT / "output/pickleball_model_latest.xlsx")],
                    check=True,
                )
                refresh_fn()
                result = ("ok", "engine rebuilt, court assignments refreshed")
            except subprocess.CalledProcessError as e:
                result = ("failed", f"rebuild step failed (exit {e.returncode}): {e}")
            except subprocess.TimeoutExpired as e:
                result = ("failed", f"rebuild step timed out: {e}")
            except Exception as e:
                result = ("failed", f"unexpected error: {e}")
    finally:
        with _REBUILD_STATE_LOCK:
            _REBUILD_STATE["pending"] -= 1
            _REBUILD_STATE["state"], _REBUILD_STATE["detail"] = result
        print(f"tryout rebuild: {result[0]} -- {result[1]}", flush=True)
# -------------------------------------------------------------------------
'''
server = replace_once(server, csv_line, state_block, "state block")

# 3. handler tail: replace the synchronous try/except + reply
start = ('        try:\n'
         '            # Re-run the engine so MANUAL_NAME_FIXES picks up the new entry\n')
end = ('            "status": "recorded, engine rebuilt, court assignments refreshed",\n'
       '        })')
assert server.count(start) == 1, f"handler start anchor: {server.count(start)} matches"
assert server.count(end) == 1, f"handler end anchor: {server.count(end)} matches"
i = server.index(start)
j = server.index(end, i) + len(end)
new_tail = '''        # Reply as soon as the name is saved. The engine rebuild + court
        # assignments refresh take minutes (about four were seen on
        # 2026-09-28), and the page showed "Load failed" during that wait even
        # though the save and the rebuild worked. The cause of that error was
        # not confirmed; replying immediately removes the long wait. The page
        # polls /api/tryout-rebuild-status for the outcome.
        with _REBUILD_STATE_LOCK:
            _REBUILD_STATE["pending"] += 1
        try:
            threading.Thread(
                target=_run_tryout_rebuild,
                args=(self._refresh_court_assignments_viewer,),
                daemon=True,
            ).start()
        except Exception as e:
            with _REBUILD_STATE_LOCK:
                _REBUILD_STATE["pending"] -= 1
            self._send_json(
                {"error": f"Recorded, but could not start the rebuild: {e}"},
                status=500)
            return
        self._send_json({
            "date": date_str, "real_name": real_name,
            "status": "saved; engine rebuild and court-assignments refresh started in the background",
        }, status=202)'''
server = server[:i] + new_tail + server[j:]

# 4. status route, right after the recorded-dates route
route = ('        elif self.path == "/api/recorded-dates":\n'
         '            self._send_json(get_recorded_dates())\n')
server = replace_once(
    server, route,
    route + ('        elif self.path == "/api/tryout-rebuild-status":\n'
             '            self._send_json(get_tryout_rebuild_status())\n'),
    "status route",
)

# ------------------------------------------------------------------ page ---

html = replace_once(
    html,
    "'Rebuilding engine and refreshing court assignments \u2014 this may take a couple minutes...'",
    "'Saving...'",
    "pending text",
)
html = replace_once(html, "statusEl.className = 'ok';", "statusEl.className = 'pending';", "ok class")
html = replace_once(
    html,
    "statusEl.textContent = `Done: ${date}'s tryout slot recorded as \"${real_name}\" \u2014 ${data.status}.`;",
    "statusEl.textContent = `Saved: ${date}'s tryout slot recorded as \"${real_name}\". "
    "Rebuilding in the background \u2014 this message updates when it finishes (a few minutes)...`;\n"
    "      pollRebuildStatus(date, real_name);",
    "success text",
)

poll_fn = '''
async function pollRebuildStatus(date, realName) {
  const statusEl = document.getElementById('status');
  const started = Date.now();
  const MAX_MS = 15 * 60 * 1000;
  while (Date.now() - started < MAX_MS) {
    await new Promise(r => setTimeout(r, 5000));
    try {
      const resp = await fetch('/api/tryout-rebuild-status');
      const s = await resp.json();
      if (s.state === 'ok') {
        statusEl.className = 'ok';
        statusEl.textContent = `Done: ${date}'s tryout slot recorded as "${realName}" \u2014 ${s.detail}.`;
        return;
      }
      if (s.state === 'failed') {
        statusEl.className = 'err';
        statusEl.textContent = `Saved, but the rebuild failed: ${s.detail}. The name is recorded; the court-assignments page may not reflect it yet.`;
        return;
      }
      if (s.state === 'idle') {
        statusEl.className = 'err';
        statusEl.textContent = 'Saved, but the server has no record of a rebuild running (it may have restarted). The name is recorded; check the court-assignments page in a few minutes.';
        return;
      }
      // state === 'running': keep waiting
    } catch (e) {
      // transient error while polling: keep trying until the time limit
    }
  }
  statusEl.className = 'err';
  statusEl.textContent = 'Saved, but the rebuild is taking longer than 15 minutes. The name is recorded; check the court-assignments page later.';
}
'''
html = replace_once(html, "</script>", poll_fn + "</script>", "script close")

server_path.write_text(server, encoding="utf-8")
html_path.write_text(html, encoding="utf-8")
print("launcher_server.py and tryout_name.html updated successfully")
