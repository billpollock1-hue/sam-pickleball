#!/usr/bin/env python3
"""
launcher_server.py

Serves the SAM Shootout Launcher control panel and its JSON API.
Stdlib only — no pip install needed.

Run manually to test:
    python3 launcher_server.py

Intended to run continuously via launchd (KeepAlive=true) on a fixed port.

Endpoints:
    GET  /                    -> control_panel.html
    GET  /api/config          -> current launcher_config.json
    POST /api/config          -> update mode / autolaunch_time_mst
    GET  /api/log?limit=N     -> most recent N launch_log.jsonl entries (newest first)
    GET  /api/next-shootout   -> {"display": "Thursday, July 16, 2026"} derived from
                                  signup_monitor_state.json's known_sheet_dates / closed flags

All actual launching happens in launcher_poller.py (run every 5 min via
launchd StartInterval) — this server is just the config/log read-write
surface for the browser panel.
"""

import json
import os
import sys
from datetime import datetime, timedelta, time as dtime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "launcher_config.json"
LOG_PATH = BASE_DIR / "launch_log.jsonl"
HTML_PATH = BASE_DIR / "control_panel.html"
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
                "last_autolaunch_date": None, "updated_at": None}
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

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            body = HTML_PATH.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
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
            save_config(cfg)
            self._send_json(cfg)
        else:
            self._send_json({"error": "not found"}, status=404)

    def log_message(self, format, *args):
        # Quiet default stderr logging; launchd captures stdout/stderr to its own log files anyway.
        pass


if __name__ == "__main__":
    if not CONFIG_PATH.exists():
        save_config({"mode": "none", "autolaunch_time_mst": "05:45", "last_autolaunch_date": None})
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Launcher control panel serving at http://127.0.0.1:{PORT}", file=sys.stderr)
    server.serve_forever()
