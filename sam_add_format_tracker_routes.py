#!/usr/bin/env python3
"""
One-off patch: adds Format Change Tracker routes to launcher_server.py.
Run once from the repo root: python3 sam_add_format_tracker_routes.py
Safe to re-run: asserts each anchor matches exactly once, so it will
fail loudly (not corrupt the file) if already applied or if the
surrounding code has changed.
"""
from pathlib import Path

path = Path("launcher/launcher_server.py")
content = path.read_text()

anchor1 = 'DATES_HTML_PATH = BASE_DIR / "dates.html"'
assert content.count(anchor1) == 1, f"anchor1 matches: {content.count(anchor1)}"
new1 = (
    anchor1
    + '\nFORMAT_TRACKER_HTML_PATH = BASE_DIR / "format_tracker.html"'
    + '\nFORMAT_TRACKER_DATA_PATH = BASE_DIR / "format_tracker_data.json"'
)
content = content.replace(anchor1, new1)

anchor2 = (
    '        elif self.path == "/dates" or self.path == "/dates.html":\n'
    '            self._send_html(DATES_HTML_PATH)'
)
assert content.count(anchor2) == 1, f"anchor2 matches: {content.count(anchor2)}"
new2 = anchor2 + (
    '\n        elif self.path == "/format_tracker.html" or self.path == "/format_tracker":'
    '\n            self._send_html(FORMAT_TRACKER_HTML_PATH)'
    '\n        elif self.path == "/format_tracker_data.json":'
    '\n            if FORMAT_TRACKER_DATA_PATH.exists():'
    '\n                body = FORMAT_TRACKER_DATA_PATH.read_bytes()'
    '\n                self.send_response(200)'
    '\n                self.send_header("Content-Type", "application/json")'
    '\n                self.send_header("Content-Length", str(len(body)))'
    '\n                self.end_headers()'
    '\n                self.wfile.write(body)'
    '\n            else:'
    '\n                self._send_json({"error": "not found"}, status=404)'
)
content = content.replace(anchor2, new2)

path.write_text(content)
print("launcher_server.py updated successfully")
