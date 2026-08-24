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
DATES_HTML_PATH = BASE_DIR / "dates.html"
REPO_ROOT = BASE_DIR.parent
NO_SHOOTOUT_CSV = REPO_ROOT / "data" / "no_shootout_dates.csv"
PARTIAL_SHOOTOUT_CSV = REPO_ROOT / "data" / "partial_shootout_dates.csv"
PORT = 8765
MST = ZoneInfo("America/Phoenix")  # Arizona, no DST — matches "MST" label used everywhere else

# Same PB_RUNTIME convention used by monitor_signups.py / refresh_assignments.py / den_assignments.py.
# TODO (Bill): confirm this default matches where signup_monitor_state.json actually lives; override
# by setting PB_RUNTIME in the environment (e.g. in the launchd plist) if it differs.
PB_RUNTIME = os.environ.get("PB_RUNTIME", str(Path.home() / "Library/Application Support/PBMonitor"))
STATE_PATH = Path(PB_RUNTIME) / "signup_monitor_state.json"


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
        elif self.path == "/api/next-shootout":
            self._send_json({"display": get_next_shootout_display()})
        elif self.path == "/dates" or self.path == "/dates.html":
            self._send_html(DATES_HTML_PATH)
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
        subprocess.run(
            ["cp", str(REPO_ROOT / "assignments/output/court_assignments_viewer.html"),
             str(REPO_ROOT / "docs/court_assignments.html")],
            check=True,
        )

    def _handle_record_date(self, payload):
        date_str = str(payload.get("date", "")).strip()
        date_type = payload.get("type")
        if not date_str or date_type not in ("none", "single"):
            self._send_json({"error": "date and type (none/single) required"}, status=400)
            return

        if date_type == "none":
            if not self._append_csv_date(NO_SHOOTOUT_CSV, date_str):
                self._send_json({"error": f"{date_str} is already recorded"}, status=409)
                return
            try:
                self._refresh_court_assignments_viewer()
            except Exception as e:
                self._send_json({"error": f"Recorded, but viewer refresh failed: {e}"}, status=500)
                return
            self._send_json({"date": date_str, "type": "none", "status": "recorded and viewer refreshed"})
            return

        # date_type == "single"
        if not self._append_csv_date(PARTIAL_SHOOTOUT_CSV, date_str):
            self._send_json({"error": f"{date_str} is already recorded"}, status=409)
            return
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
            self._refresh_court_assignments_viewer()
        except subprocess.CalledProcessError as e:
            self._send_json({"error": f"Pipeline step failed (exit {e.returncode}): {e}"}, status=500)
            return
        except subprocess.TimeoutExpired as e:
            self._send_json({"error": f"Pipeline step timed out: {e}"}, status=500)
            return
        self._send_json({
            "date": date_str, "type": "single",
            "status": "scraped, merged, engine rebuilt, viewer refreshed",
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
