#!/usr/bin/env python3
"""
Singing Clock - Local Server
Serves the dashboard and provides a /api/scan endpoint to trigger rescans.

Usage: python3 server.py [port]
Default port: 8080
"""

import http.server
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
PROJECT_DIR = Path(__file__).parent

# Track scan state
scan_lock = threading.Lock()
scan_running = False


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PROJECT_DIR), **kwargs)

    def do_GET(self):
        if self.path == "/api/scan":
            self.handle_scan()
        elif self.path == "/api/status":
            self.handle_status()
        elif self.path == "/":
            self.path = "/index.html"
            super().do_GET()
        else:
            super().do_GET()

    def handle_scan(self):
        global scan_running
        if scan_running:
            self.send_json({"status": "already_running"}, 409)
            return

        def run_scan():
            global scan_running
            scan_running = True
            try:
                result = subprocess.run(
                    [sys.executable, str(PROJECT_DIR / "scan.py")],
                    capture_output=True, text=True, timeout=300,
                    cwd=str(PROJECT_DIR),
                )
                return result.returncode == 0, result.stdout + result.stderr
            except Exception as e:
                return False, str(e)
            finally:
                scan_running = False

        # Run scan in background thread, return immediately
        self.send_json({"status": "started"})

        thread = threading.Thread(target=run_scan, daemon=True)
        thread.start()

    def handle_status(self):
        data_file = PROJECT_DIR / "data.json"
        if data_file.exists():
            try:
                with open(data_file) as f:
                    d = json.load(f)
                self.send_json({
                    "scan_running": scan_running,
                    "last_scan": d.get("generated"),
                    "total_commits": d.get("total_commits"),
                })
            except Exception:
                self.send_json({"scan_running": scan_running, "last_scan": None})
        else:
            self.send_json({"scan_running": scan_running, "last_scan": None})

    def send_json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        if "/api/" in (args[0] if args else ""):
            super().log_message(format, *args)


if __name__ == "__main__":
    server = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Singing Clock server running at http://localhost:{PORT}")
    print(f"Press Ctrl+C to stop\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
