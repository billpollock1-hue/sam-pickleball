#!/usr/bin/env python3
"""
launcher_server.py

Serves the SAM Pickleball admin panel: an index page at "/" linking to
operational tools (currently just the Shootout Launcher control panel,
at "/launcher"; more tools -- player-name-edit and no-shootout-date
management -- planned as later additions to this same index). Stdlib
only -- no pip install needed.

Run manually to test:
    python3 launcher_server.py

Intended to run continuously via launchd (KeepAlive=true) on a fixed port.

Binds to 0.0.0.0 (not 127.0.0.1) so it's reachable from other devices on
the same home network -- e.g. a MacBook -- not just this Mac. No
authentication: anyone on the home network can reach it and trigger real
automated actions (deliberate choice, single-user/trusted-network use).

Endpoints:
    GET  /                    -> admin_index.html
    GET  /launcher            -> control_panel.html (the Shootout Launcher)
    GET  /api/config          -> current launcher_config.json
    POST /api/config          -> update mode / autolaunch_time_mst
    GET  /api/log?limit=N     -> most recent N launch_log.jsonl entries (newest first)
    GET  /api/next-shootout   -> {"display": "Thursday, July 16, 2026"} derived from
                                  signup_monitor_state.json's known_sheet_dates / closed flags

All actual launching happens in launcher_poller.py (run every 5 min via
launchd StartInterval) — this server is just the config/log read-write
surface for the browser panel(s).
"""

import json
import os
import socket
import subprocess
import threading
import sys
from datetime import datetime, timedelta, time as dtime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "launcher_config.json"
LOG_PATH = BASE_DIR / "launch_log.jsonl"
HTML_PATH = BASE_DIR / "control_panel.html"
ADMIN_INDEX_PATH = BASE_DIR / "admin_index.html"
CYCLE_LOG_PATH = BASE_DIR / "cycle_log.jsonl"
CYCLE_LOG_HTML_PATH = BASE_DIR / "cycle_log.html"
DATES_HTML_PATH = BASE_DIR / "dates.html"
TRYOUT_NAME_HTML_PATH = BASE_DIR / "tryout_name.html"
FORMAT_TRACKER_HTML_PATH = BASE_DIR / "format_tracker.html"
FORMAT_TRACKER_DATA_PATH = BASE_DIR / "format_tracker_data.json"
REPO_ROOT = BASE_DIR.parent
NO_SHOOTOUT_CSV = REPO_ROOT / "data" / "no_shootout_dates.csv"
PARTIAL_SHOOTOUT_CSV = REPO_ROOT / "data" / "partial_shootout_dates.csv"
TRYOUT_NAME_FIXES_CSV = REPO_ROOT / "data" / "tryout_name_fixes.csv"

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


_RECORD_DATE_STATE_LOCK = threading.Lock()
_RECORD_DATE_STATE = {"pending": 0, "state": "idle", "detail": ""}


def get_record_date_status():
    with _RECORD_DATE_STATE_LOCK:
        if _RECORD_DATE_STATE["pending"] > 0:
            return {"state": "running", "detail": ""}
        return {"state": _RECORD_DATE_STATE["state"], "detail": _RECORD_DATE_STATE["detail"]}


def _run_single_shootout_pipeline(date_str, refresh_fn):
    """Background thread body for the 'single shootout' record-date
    path. Shares _REBUILD_LOCK with the tryout-name pipeline below --
    both write to the same /tmp/pickleball_model_latest.xlsx, so they
    must never run concurrently."""
    result = ("failed", "pipeline did not run")
    try:
        with _REBUILD_LOCK:
            try:
                parsed = datetime.strptime(date_str, "%Y-%m-%d")
                scrape_date = parsed.strftime("%m%d%y")
                subprocess.run(
                    ["node", "scraper/scrape.js", "--start", scrape_date, "--end", scrape_date,
                     "--output", "data/latest_scrape.csv"],
                    cwd=REPO_ROOT, check=True, timeout=120,
                )
                subprocess.run(
                    ["python3", "scraper/merge_csv.py"],
                    cwd=REPO_ROOT, check=True, timeout=60,
                )
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
                _launch_update_cycle_now(False)
                result = ("ok", "scraped, merged, engine rebuilt, viewer refreshed, update cycle started")
            except subprocess.CalledProcessError as e:
                result = ("failed", f"pipeline step failed (exit {e.returncode}): {e}")
            except subprocess.TimeoutExpired as e:
                result = ("failed", f"pipeline step timed out: {e}")
            except Exception as e:
                result = ("failed", f"unexpected error: {e}")
    finally:
        with _RECORD_DATE_STATE_LOCK:
            _RECORD_DATE_STATE["pending"] -= 1
            _RECORD_DATE_STATE["state"], _RECORD_DATE_STATE["detail"] = result
        print(f"single-shootout record-date pipeline: {result[0]} -- {result[1]}", flush=True)


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
SHOOTOUT_TIES_CSV = REPO_ROOT / "data" / "shootout_leader_overrides.csv"
SHOOTOUT_TIES_HTML_PATH = BASE_DIR / "shootout_ties.html"
PORT = 8765
MST = ZoneInfo("America/Phoenix")  # Arizona, no DST — matches "MST" label used everywhere else

# Same PB_RUNTIME convention used by monitor_signups.py / refresh_assignments.py / den_assignments.py.
# TODO (Bill): confirm this default matches where signup_monitor_state.json actually lives; override
# by setting PB_RUNTIME in the environment (e.g. in the launchd plist) if it differs.
PB_RUNTIME = os.environ.get("PB_RUNTIME", str(Path.home() / "Library/Application Support/PBMonitor"))
STATE_PATH = Path(PB_RUNTIME) / "signup_monitor_state.json"


def get_recorded_tryout_names():
    """Read data/tryout_name_fixes.csv and return it sorted newest-first,
    for the Identify Tryout Player page's log."""
    entries = []
    if TRYOUT_NAME_FIXES_CSV.exists():
        lines = TRYOUT_NAME_FIXES_CSV.read_text().splitlines()[1:]  # skip header
        for line in lines:
            line = line.strip()
            if not line:
                continue
            date_str, real_name = line.split(",", 1)
            entries.append({"date": date_str.strip(), "real_name": real_name.strip()})
    entries.sort(key=lambda e: e["date"], reverse=True)
    return entries[:10]  # most recent 10 only -- requested so this log stays short


# ---- Immediate update cycle helpers (admin "Adjust Shootouts for a Weekday") ----
UPDATE_CYCLE_LABEL = "com.pickleballden.shootout-scraper"
RUN_ALL_LOCKDIR = Path("/tmp/sam_pickleball_run_all.lockdir")


def _ps_table():
    """pid -> (ppid, command) for every process."""
    out = subprocess.run(["ps", "-axo", "pid=,ppid=,command="],
                         capture_output=True, text=True, timeout=10).stdout
    table = {}
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            table[int(parts[0])] = (int(parts[1]), parts[2])
    return table


def _descends_from(pid, ancestor, table):
    for _ in range(8):
        if pid == ancestor:
            return True
        row = table.get(pid)
        if not row:
            return False
        pid = row[0]
    return False


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _run_all_lock_pid():
    """PID of a live run_all.sh cycle, or None."""
    try:
        pid = int((RUN_ALL_LOCKDIR / "pid").read_text().strip())
    except Exception:
        return None
    return pid if _pid_alive(pid) else None


def _sweep_orphan_chromium():
    """Kill Playwright Chromium main processes orphaned (ppid 1) by a killed
    scrape. Their helper processes exit with them. A live scrape's browser
    has a live parent, so it is never matched."""
    import signal as _signal
    killed = []
    for pid, (ppid, cmd) in _ps_table().items():
        if ppid == 1 and "playwright_chromiumdev_profile" in cmd and "--type=" not in cmd:
            try:
                os.kill(pid, _signal.SIGTERM)
                killed.append(pid)
            except OSError:
                pass
    if killed:
        print(f"[update-cycle] swept orphaned Chromium pid(s) {killed}", flush=True)


def _launch_update_cycle_now(abort_scrape):
    """Start the launchd update cycle right now instead of waiting for its
    15-minute interval. With abort_scrape, first kill an in-flight scrape
    belonging to a running cycle -- but only if that cycle is still in its
    scrape step; a cycle already building or publishing is left to finish.
    Blocking (may wait ~45s): always call from a background thread."""
    import signal as _signal
    import time as _time
    dry = os.environ.get("SAM_UPDATE_CYCLE_DRY_RUN") == "1"
    tag = "[update-cycle]" + (" (DRY RUN)" if dry else "")
    try:
        if abort_scrape:
            lock_pid = _run_all_lock_pid()
            if lock_pid:
                table = _ps_table()
                targets = [pid for pid, (_pp, cmd) in table.items()
                           if pid != lock_pid and "scraper/scrape.js" in cmd and _descends_from(pid, lock_pid, table)]
                if targets:
                    print(f"{tag} aborting in-flight scrape pid(s) {targets} of cycle {lock_pid}", flush=True)
                    if not dry:
                        for pid in targets:
                            try:
                                os.kill(pid, _signal.SIGTERM)
                            except OSError:
                                pass
                        deadline = _time.time() + 15
                        while _time.time() < deadline and any(_pid_alive(p) for p in targets):
                            _time.sleep(0.5)
                        for pid in targets:
                            if _pid_alive(pid):
                                try:
                                    os.kill(pid, _signal.SIGKILL)
                                except OSError:
                                    pass
                        _sweep_orphan_chromium()
                        # run_all.sh exits on a scraper failure and its trap
                        # releases the lock; wait for that, or the new cycle
                        # would see "already running" and exit.
                        deadline = _time.time() + 30
                        while _time.time() < deadline and RUN_ALL_LOCKDIR.exists():
                            _time.sleep(0.5)
                else:
                    print(f"{tag} cycle {lock_pid} is running but not in its scrape step -- leaving it to finish", flush=True)
        label = f"gui/{os.getuid()}/{UPDATE_CYCLE_LABEL}"
        if dry:
            print(f"{tag} would run: launchctl kickstart {label}", flush=True)
            return
        r = subprocess.run(["launchctl", "kickstart", label],
                           capture_output=True, text=True, timeout=20)
        print(f"{tag} launchctl kickstart exit {r.returncode} {r.stderr.strip()}", flush=True)
    except Exception as e:
        print(f"{tag} failed: {e} (the normal 15-minute cycle will still run)", flush=True)


def get_recorded_dates():
    """Read both no-shootout and partial-shootout CSVs, tag each
    entry with its type, and return combined, sorted newest-first."""
    entries = []
    for csv_path, date_type in (
        (NO_SHOOTOUT_CSV, "none"),
        (PARTIAL_SHOOTOUT_CSV, "single"),
    ):
        if not csv_path.exists():
            continue
        lines = csv_path.read_text().splitlines()[1:]  # skip header
        for line in lines:
            date_str = line.split(",")[0].strip()  # tolerant of an optional source column
            if date_str:
                entries.append({"date": date_str, "type": date_type})
    entries.sort(key=lambda e: e["date"], reverse=True)
    return entries


def get_unresolved_ties():
    """Rows in the shootout-leader-overrides CSV with a blank winner --
    pools where the wins+margin tiebreak couldn't pick a single leader,
    so no shootout bear was awarded pending manual resolution here.
    build_bear_count.py appends new ones automatically as it finds them."""
    if not SHOOTOUT_TIES_CSV.exists():
        return []
    import csv
    with open(SHOOTOUT_TIES_CSV, newline="") as f:
        rows = list(csv.DictReader(f))
    pending = []
    for r in rows:
        if not r.get("winner", "").strip():
            pending.append({
                "play_date": r["play_date"],
                "shootout": r["shootout"],
                "pool": r["pool"],
                "tied_candidates": [n.strip() for n in r["tied_candidates"].split("/")],
            })
    pending.sort(key=lambda t: t["play_date"])
    return pending


def load_config():
    if not CONFIG_PATH.exists():
        return {"mode": "none", "autolaunch_time_mst": "05:45",
                "last_autolaunch_date": None, "updated_at": None,
                "shuffle_mode": "2u2b"}
    return json.loads(CONFIG_PATH.read_text())


def save_config(cfg):
    cfg["updated_at"] = datetime.now(MST).isoformat()
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def read_log(limit=50):
    if not LOG_PATH.exists():
        return []
    lines = LOG_PATH.read_text().splitlines()
    entries = [json.loads(l) for l in lines if l.strip()]
    return list(reversed(entries))[:limit]


def read_cycle_log(limit=100):
    """Join start/progress/end records from cycle_log.jsonl (written by run_all.sh)
    into one row per pass, newest first.

    A start with no end older than 45 minutes is "unfinished" (killed mid-run,
    e.g. the Mac went to sleep); a younger one is "running". Only the tail of
    the file is read, so the page stays fast as the log grows.
    """
    if not CYCLE_LOG_PATH.exists():
        return []
    limit = max(1, min(int(limit), 2000))
    tail_bytes = limit * 4 * 1500 + 4096
    with open(CYCLE_LOG_PATH, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - tail_bytes))
        raw = f.read().decode("utf-8", errors="replace")
    runs = {}
    order = []
    for line in raw.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue  # partial first line from the tail read, or a bad line
        rid = rec.get("run_id")
        if not rid:
            continue
        if rid not in runs:
            runs[rid] = {"run_id": rid, "started": None, "finished": None,
                         "status": "running", "duration_s": None}
            order.append(rid)
        r = runs[rid]
        ev = rec.get("event")
        if ev == "start":
            r["started"] = rec.get("timestamp")
        elif ev in ("progress", "end"):
            for k, v in rec.items():
                if k not in ("run_id", "event", "timestamp") and v is not None:
                    r[k] = v
            if ev == "end":
                r["finished"] = rec.get("timestamp")

    def _parse(ts):
        try:
            return datetime.strptime(ts.replace(" MST", ""), "%Y-%m-%d %H:%M:%S").replace(tzinfo=MST)
        except (AttributeError, ValueError):
            return None

    now = datetime.now(MST)
    out = []
    for rid in order:
        r = runs[rid]
        started_dt = _parse(r["started"])
        finished_dt = _parse(r["finished"])
        if r["started"] is None and finished_dt and r.get("duration_s") is not None:
            started_dt = finished_dt - timedelta(seconds=r["duration_s"])
            r["started"] = started_dt.strftime("%Y-%m-%d %H:%M:%S MST")
        if r["finished"] is None and started_dt:
            age_min = (now - started_dt).total_seconds() / 60
            r["status"] = "unfinished" if age_min > 45 else "running"
        ref = finished_dt or started_dt
        r["finished_ago_min"] = round((now - ref).total_seconds() / 60, 1) if ref else None
        out.append(r)
    out.sort(key=lambda r: r["started"] or r["finished"] or "", reverse=True)
    return out[:limit]


def _next_weekday_fallback():
    """Used only if signup_monitor_state.json is missing/unreadable."""
    now = datetime.now(MST)
    d = now.date()
    if d.weekday() < 5 and now.time() < dtime(6, 0):
        target = d
    else:
        target = d + timedelta(days=1)
        while target.weekday() >= 5:
            target += timedelta(days=1)
    return datetime(target.year, target.month, target.day).strftime("%A, %B %-d, %Y")


def get_next_shootout_display():
    try:
        state = json.loads(STATE_PATH.read_text())
        known_dates = sorted(state.get("known_sheet_dates", []))
        snapshots = state.get("snapshots", {})
        today_str = datetime.now(MST).date().isoformat()

        for d in known_dates:
            if d < today_str:
                continue
            snap = snapshots.get(d, {})
            if not snap.get("closed", False):
                dt = datetime.strptime(d, "%Y-%m-%d")
                return dt.strftime("%A, %B %-d, %Y")
        # Every known date is closed (e.g. state file hasn't picked up the next
        # sheet yet) — fall back to weekday logic rather than showing nothing.
        return _next_weekday_fallback()
    except Exception:
        return _next_weekday_fallback()


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, path):
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._send_html(ADMIN_INDEX_PATH)
        elif self.path == "/launcher" or self.path == "/launcher.html" or self.path == "/launcher/":
            self._send_html(HTML_PATH)
        elif self.path == "/api/config":
            self._send_json(load_config())
        elif self.path.startswith("/api/log"):
            limit = 50
            if "limit=" in self.path:
                try:
                    limit = int(self.path.split("limit=")[1].split("&")[0])
                except ValueError:
                    pass
            self._send_json(read_log(limit))
        elif self.path == "/cycle-log" or self.path == "/cycle_log.html":
            self._send_html(CYCLE_LOG_HTML_PATH)
        elif self.path.startswith("/api/cycle-log"):
            limit = 100
            if "limit=" in self.path:
                try:
                    limit = int(self.path.split("limit=")[1].split("&")[0])
                except ValueError:
                    pass
            self._send_json(read_cycle_log(limit))
        elif self.path == "/api/next-shootout":
            self._send_json({"display": get_next_shootout_display()})
        elif self.path == "/api/recorded-dates":
            self._send_json(get_recorded_dates())
        elif self.path == "/api/tryout-rebuild-status":
            self._send_json(get_tryout_rebuild_status())
        elif self.path == "/api/record-date-status":
            self._send_json(get_record_date_status())
        elif self.path == "/api/recorded-tryout-names":
            self._send_json(get_recorded_tryout_names())
        elif self.path == "/dates" or self.path == "/dates.html":
            self._send_html(DATES_HTML_PATH)
        elif self.path == "/tryout-name" or self.path == "/tryout_name.html":
            self._send_html(TRYOUT_NAME_HTML_PATH)
        elif self.path == "/format_tracker.html" or self.path == "/format_tracker":
            self._send_html(FORMAT_TRACKER_HTML_PATH)
        elif self.path == "/api/unresolved-ties":
            self._send_json(get_unresolved_ties())
        elif self.path == "/shootout-ties" or self.path == "/shootout_ties.html":
            self._send_html(SHOOTOUT_TIES_HTML_PATH)
        elif self.path == "/format_tracker_data.json":
            if FORMAT_TRACKER_DATA_PATH.exists():
                body = FORMAT_TRACKER_DATA_PATH.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._send_json({"error": "not found"}, status=404)
        else:
            self._send_json({"error": "not found"}, status=404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            payload = {}

        if self.path == "/api/config":
            cfg = load_config()
            if payload.get("mode") in ("none", "step_percent", "elo_autolaunch"):
                cfg["mode"] = payload["mode"]
            if payload.get("autolaunch_time_mst"):
                cfg["autolaunch_time_mst"] = payload["autolaunch_time_mst"]
            if payload.get("shuffle_mode") in ("2u2b", "1u1b2s"):
                cfg["shuffle_mode"] = payload["shuffle_mode"]
            save_config(cfg)
            self._send_json(cfg)
        elif self.path == "/api/record-date":
            self._handle_record_date(payload)
        elif self.path == "/api/delete-recorded-date":
            self._handle_delete_recorded_date(payload)
        elif self.path == "/api/record-tryout-name":
            self._handle_record_tryout_name(payload)
        elif self.path == "/api/resolve-shootout-tie":
            self._handle_resolve_shootout_tie(payload)
        else:
            self._send_json({"error": "not found"}, status=404)

    def _append_csv_date(self, csv_path, date_str):
        existing = set()
        if csv_path.exists():
            existing = set(
                line.strip() for line in csv_path.read_text().splitlines()[1:] if line.strip()
            )
        if date_str in existing:
            return False
        with open(csv_path, "a") as f:
            f.write(f"{date_str}\n")
        return True

    def _refresh_court_assignments_viewer(self):
        subprocess.run(
            ["python3", "generate_assignments_viewer.py"],
            cwd=REPO_ROOT / "assignments", check=True, timeout=60,
        )
        # Copy to a temp name, then rename over the destination. A rename never
        # has to read or rewrite the old file, so it works even when macOS has
        # evicted docs/court_assignments.html to the cloud ("dataless"), where an
        # in-place cp fails with "Resource deadlock avoided" (2026-10-13).
        src = REPO_ROOT / "assignments/output/court_assignments_viewer.html"
        tmp_dest = REPO_ROOT / "assignments/output/.court_assignments_docs.tmp"
        subprocess.run(["cp", str(src), str(tmp_dest)], check=True)
        os.replace(tmp_dest, REPO_ROOT / "docs/court_assignments.html")

    def _handle_delete_recorded_date(self, payload):
        date_str = str(payload.get("date", "")).strip()
        date_type = payload.get("type")
        if not date_str or date_type not in ("none", "single"):
            self._send_json({"error": "date and type (none/single) required"}, status=400)
            return
        csv_path = NO_SHOOTOUT_CSV if date_type == "none" else PARTIAL_SHOOTOUT_CSV
        if not csv_path.exists():
            self._send_json({"error": f"{date_str} is not recorded"}, status=404)
            return
        lines = csv_path.read_text().splitlines()
        if not lines:
            self._send_json({"error": f"{date_str} is not recorded"}, status=404)
            return
        header, body = lines[0], lines[1:]
        kept, removed = [], False
        for line in body:
            fields = [f.strip() for f in line.split(",")]
            if fields and fields[0] == date_str:
                source = fields[1] if len(fields) > 1 else ""
                if date_type == "none" and source not in ("manual", ""):
                    self._send_json({"error": f"{date_str} was logged automatically (source: {source}); "
                                              "the signup monitor manages those itself"}, status=403)
                    return
                removed = True
                continue
            kept.append(line)
        if not removed:
            self._send_json({"error": f"{date_str} is not recorded"}, status=404)
            return
        tmp = csv_path.with_suffix(csv_path.suffix + ".tmp")
        tmp.write_text("\n".join([header] + kept) + "\n")
        os.replace(tmp, csv_path)
        try:
            self._refresh_court_assignments_viewer()
        except Exception as e:
            threading.Thread(target=_launch_update_cycle_now, args=(False,), daemon=True).start()
            self._send_json({"error": f"Removed, but viewer refresh failed: {e} -- the update cycle was started and will rebuild it"}, status=500)
            return
        threading.Thread(target=_launch_update_cycle_now, args=(False,), daemon=True).start()
        self._send_json({"date": date_str, "type": date_type,
                         "status": "removed and viewer refreshed; update cycle starting now"})

    def _handle_record_date(self, payload):
        date_str = str(payload.get("date", "")).strip()
        date_type = payload.get("type")
        if not date_str or date_type not in ("none", "single"):
            self._send_json({"error": "date and type (none/single) required"}, status=400)
            return

        if date_type == "none":
            # Tagged "manual" (distinct from check_no_shootout.py's own
            # "auto" entries) so its self-correction logic never silently
            # reverts a deliberate admin-panel cancellation -- real
            # incident 2026-09-28: an auto-removal erased one within
            # the same run_all.sh cycle.
            existing_dates = set()
            if NO_SHOOTOUT_CSV.exists():
                existing_dates = {
                    line.split(",")[0].strip()
                    for line in NO_SHOOTOUT_CSV.read_text().splitlines()[1:]
                    if line.strip()
                }
            if date_str in existing_dates:
                self._send_json({"error": f"{date_str} is already recorded"}, status=409)
                return
            if not NO_SHOOTOUT_CSV.exists():
                NO_SHOOTOUT_CSV.write_text("date,source\n")
            with open(NO_SHOOTOUT_CSV, "a") as f:
                f.write(f"{date_str},manual\n")
            try:
                self._refresh_court_assignments_viewer()
            except Exception as e:
                threading.Thread(target=_launch_update_cycle_now, args=(True,), daemon=True).start()
                self._send_json({"error": f"Recorded, but viewer refresh failed: {e} -- the update cycle was started and will rebuild it"}, status=500)
                return
            threading.Thread(target=_launch_update_cycle_now, args=(True,), daemon=True).start()
            self._send_json({"date": date_str, "type": "none",
                             "status": "recorded and viewer refreshed; update cycle starting now"})
            return

        # date_type == "single"
        # Reply as soon as the date is saved; the scrape/merge/rebuild/
        # refresh pipeline runs in the background and this page polls
        # /api/record-date-status for the outcome -- real incident
        # 2026-09-30: this request used to stay open through the whole
        # pipeline and "Load failed" in the browser even when the work
        # eventually succeeded.
        if not self._append_csv_date(PARTIAL_SHOOTOUT_CSV, date_str):
            self._send_json({"error": f"{date_str} is already recorded"}, status=409)
            return
        with _RECORD_DATE_STATE_LOCK:
            _RECORD_DATE_STATE["pending"] += 1
        try:
            threading.Thread(
                target=_run_single_shootout_pipeline,
                args=(date_str, self._refresh_court_assignments_viewer),
                daemon=True,
            ).start()
        except Exception as e:
            with _RECORD_DATE_STATE_LOCK:
                _RECORD_DATE_STATE["pending"] -= 1
            self._send_json(
                {"error": f"Recorded, but could not start the pipeline: {e}"},
                status=500)
            return
        self._send_json({
            "date": date_str, "type": "single",
            "status": "saved; scrape/merge/rebuild pipeline started in the background",
        }, status=202)

    def _handle_record_tryout_name(self, payload):
        date_str = str(payload.get("date", "")).strip()
        real_name = str(payload.get("real_name", "")).strip()
        if not date_str or not real_name:
            self._send_json({"error": "date and real_name required"}, status=400)
            return

        # Two-column CSV (date,real_name) -- distinct from _append_csv_date's
        # single-column helper above. Companion to pickleball_engine_v2.py's
        # MANUAL_NAME_FIXES (historical rating correction, applied once the
        # date's games are scraped) and den_assignments.py's
        # assign_courts_by_rating (pre-play court-seeding preview) -- both
        # read this same file, so recording it here is the one action that
        # keeps score history, the court-assignments page, and the shootout
        # launcher's seeding all consistent.
        existing_rows = []
        if TRYOUT_NAME_FIXES_CSV.exists():
            existing_rows = [
                line.strip() for line in TRYOUT_NAME_FIXES_CSV.read_text().splitlines()[1:]
                if line.strip()
            ]
        for row in existing_rows:
            if row.split(",")[0].strip() == date_str:
                self._send_json({"error": f"{date_str} is already recorded"}, status=409)
                return
        if not TRYOUT_NAME_FIXES_CSV.exists():
            TRYOUT_NAME_FIXES_CSV.write_text("date,real_name\n")
        with open(TRYOUT_NAME_FIXES_CSV, "a") as f:
            f.write(f"{date_str},{real_name}\n")

        # Reply as soon as the name is saved. The engine rebuild + court
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
        }, status=202)

    def _handle_resolve_shootout_tie(self, payload):
        play_date = str(payload.get("play_date", "")).strip()
        shootout = str(payload.get("shootout", "")).strip()
        pool = str(payload.get("pool", "")).strip()
        winner = str(payload.get("winner", "")).strip()
        if not (play_date and shootout and pool and winner):
            self._send_json({"error": "play_date, shootout, pool, and winner are required"}, status=400)
            return

        import csv
        if not SHOOTOUT_TIES_CSV.exists():
            self._send_json({"error": "no overrides file found"}, status=404)
            return
        with open(SHOOTOUT_TIES_CSV, newline="") as f:
            rows = list(csv.DictReader(f))

        matched = False
        for r in rows:
            if (r["play_date"], str(r["shootout"]), r["pool"]) == (play_date, shootout, pool):
                candidates = [n.strip() for n in r["tied_candidates"].split("/")]
                if winner not in candidates:
                    self._send_json(
                        {"error": f'"{winner}" wasn\'t one of the tied candidates for this pool'},
                        status=400)
                    return
                r["winner"] = winner
                matched = True
                break
        if not matched:
            self._send_json({"error": "no matching tie found for that date/shootout/pool"}, status=404)
            return

        with open(SHOOTOUT_TIES_CSV, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["play_date", "shootout", "pool", "tied_candidates", "winner"])
            w.writeheader()
            w.writerows(rows)

        try:
            subprocess.run(
                ["python3", "engine/build_bear_count.py"],
                cwd=REPO_ROOT, check=True, timeout=120,
            )
            subprocess.run(
                ["cp", str(REPO_ROOT / "output/bear_count.html"), str(REPO_ROOT / "docs/bear_count.html")],
                check=True,
            )
        except subprocess.CalledProcessError as e:
            self._send_json({"error": f"Recorded, but Bear Count rebuild failed (exit {e.returncode}): {e}"}, status=500)
            return
        except subprocess.TimeoutExpired as e:
            self._send_json({"error": f"Recorded, but Bear Count rebuild timed out: {e}"}, status=500)
            return

        self._send_json({
            "play_date": play_date, "shootout": shootout, "pool": pool, "winner": winner,
            "status": "Bear Count rebuilt",
        })

    def log_message(self, format, *args):
        # Quiet default stderr logging; launchd captures stdout/stderr to its own log files anyway.
        pass


if __name__ == "__main__":
    if not CONFIG_PATH.exists():
        save_config({"mode": "none", "autolaunch_time_mst": "05:45", "last_autolaunch_date": None})
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        lan_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        lan_ip = "<this Mac's LAN IP — check System Settings > Wi-Fi/Network>"
    print(f"Admin panel serving at http://127.0.0.1:{PORT} (this Mac) "
          f"and http://{lan_ip}:{PORT} (LAN — e.g. from your MacBook)", file=sys.stderr)
    server.serve_forever()
