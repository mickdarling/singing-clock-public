#!/usr/bin/env python3
"""
Singing Clock - Local Server
Serves the dashboard and provides a /api/scan endpoint to trigger rescans.

Usage: python3 server.py [port]
Default port: 8080
"""

import http.server
import json
import subprocess
import sys
import threading
from pathlib import Path

from datetime import datetime, timezone

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
PROJECT_DIR = Path(__file__).parent


def _now_iso():
    return datetime.now(timezone.utc).isoformat()

# Track scan state
scan_lock = threading.Lock()
scan_running = False
last_scan_result = {"success": None, "output": "", "timestamp": None}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PROJECT_DIR), **kwargs)

    def do_GET(self):
        if self.path == "/api/scan":
            self.handle_scan()
        elif self.path == "/api/status":
            self.handle_status()
        elif self.path == "/api/scan-logs":
            self.handle_scan_logs()
        elif self.path == "/":
            self.path = "/index.html"
            super().do_GET()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/scan":
            self.handle_scan()
        else:
            self.send_error(405, "Method not allowed")

    def handle_scan(self):
        global scan_running
        if scan_running:
            self.send_json({"status": "already_running"}, 409)
            return

        def run_scan():
            global scan_running, last_scan_result
            scan_running = True
            try:
                result = subprocess.run(
                    [sys.executable, str(PROJECT_DIR / "scan.py")],
                    capture_output=True, text=True, timeout=300,
                    cwd=str(PROJECT_DIR),
                )
                output = result.stdout + result.stderr
                success = result.returncode == 0
                last_scan_result = {
                    "success": success,
                    "output": output[-10000:],  # keep last 10K chars
                    "timestamp": _now_iso(),
                    "returncode": result.returncode,
                }
            except subprocess.TimeoutExpired:
                last_scan_result = {
                    "success": False,
                    "output": "Scan timed out after 5 minutes",
                    "timestamp": _now_iso(),
                    "returncode": -1,
                }
            except Exception as e:
                last_scan_result = {
                    "success": False,
                    "output": str(e),
                    "timestamp": _now_iso(),
                    "returncode": -1,
                }
            finally:
                scan_running = False

        # Run scan in background thread, return immediately
        self.send_json({"status": "started"})

        thread = threading.Thread(target=run_scan, daemon=True)
        thread.start()

    def handle_status(self):
        global last_scan_result
        status = {"scan_running": scan_running, "status": "running" if scan_running else "idle"}
        data_file = PROJECT_DIR / "data.json"
        if data_file.exists():
            try:
                with open(data_file) as f:
                    d = json.load(f)
                status["last_scan"] = d.get("generated")
                status["total_commits"] = d.get("total_commits")
                status["repos_scanned"] = d.get("repos_scanned")
            except Exception:
                status["last_scan"] = None
        else:
            status["last_scan"] = None
        if last_scan_result["success"] is not None:
            status["last_scan_success"] = last_scan_result["success"]
            status["last_scan_timestamp"] = last_scan_result["timestamp"]
        self.send_json(status)

    def handle_scan_logs(self):
        self.send_json({
            "success": last_scan_result["success"],
            "output": last_scan_result["output"],
            "timestamp": last_scan_result["timestamp"],
            "scan_running": scan_running,
        })

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
