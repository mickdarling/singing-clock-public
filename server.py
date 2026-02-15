#!/usr/bin/env python3
"""
Singing Clock - Local Server
Serves the dashboard and provides a /api/scan endpoint to trigger rescans.

Usage: python3 server.py [port] [--bind-all]
Default port: 8080
Default bind: 127.0.0.1 (use --bind-all for 0.0.0.0)
"""

import http.server
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from datetime import datetime, timezone

_positional = [a for a in sys.argv[1:] if not a.startswith("--")]
try:
    PORT = int(_positional[0]) if _positional else 8080
    if not 1 <= PORT <= 65535:
        raise ValueError(f"Port must be between 1 and 65535, got {PORT}")
except (ValueError, IndexError) as e:
    print(f"Error: {e}", file=sys.stderr)
    print("Usage: python3 server.py [port] [--bind-all]", file=sys.stderr)
    sys.exit(1)
PROJECT_DIR = Path(__file__).parent


def _now_iso():
    return datetime.now(timezone.utc).isoformat()

# Track scan state
scan_lock = threading.Lock()
scan_running = False
last_scan_result = {"success": None, "output": "", "timestamp": None}


def _is_safe_path(path_str):
    """Validate that a path resolves to somewhere under the user's home directory."""
    try:
        resolved = Path(os.path.expanduser(path_str)).resolve()
        return resolved.is_relative_to(Path.home().resolve())
    except (ValueError, RuntimeError, OSError):
        return False


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PROJECT_DIR), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/scan":
            self.handle_scan()
        elif path == "/api/status":
            self.handle_status()
        elif path == "/api/scan-logs":
            self.handle_scan_logs()
        elif path == "/api/config":
            self.handle_config_get()
        elif path == "/api/repos/discover":
            self.handle_repos_discover(parsed.query)
        elif path == "/":
            self.path = "/index.html"
            super().do_GET()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/scan":
            self.handle_scan()
        else:
            self.send_error(405, "Method not allowed")

    def do_PUT(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/config":
            self.handle_config_put()
        else:
            self.send_error(405, "Method not allowed")

    def handle_scan(self):
        global scan_running
        with scan_lock:
            if scan_running:
                self.send_json({"status": "already_running"}, 409)
                return
            scan_running = True

        def run_scan():
            global scan_running, last_scan_result
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
                with scan_lock:
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

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length > 102400:  # 100KB limit
            return None
        return self.rfile.read(length)

    def handle_config_get(self):
        config_file = PROJECT_DIR / "config.json"
        example_file = PROJECT_DIR / "config.example.json"
        if config_file.exists():
            try:
                with open(config_file) as f:
                    config = json.load(f)
                self.send_json(config)
                return
            except Exception:
                pass
        if example_file.exists():
            try:
                with open(example_file) as f:
                    config = json.load(f)
                config["_is_example"] = True
                self.send_json(config)
                return
            except Exception:
                pass
        self.send_json({
            "_is_example": True,
            "repos": {"scan_dirs": [], "broad_scan": {"root": "~/Developer", "max_depth": 4}, "skip_patterns": []},
            "goal": {"name": "Self-sufficient AI system", "inception_date": "2025-06-30"},
        })

    def handle_config_put(self):
        body = self.read_body()
        if body is None:
            self.send_json({"error": "Request body too large"}, 413)
            return
        try:
            config = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            self.send_json({"error": "Invalid JSON"}, 400)
            return
        if not isinstance(config, dict):
            self.send_json({"error": "Config must be a JSON object"}, 400)
            return
        # Remove internal flags
        config.pop("_is_example", None)
        # Schema validation
        repos_section = config.get("repos")
        if repos_section is not None and not isinstance(repos_section, dict):
            self.send_json({"error": "repos must be an object"}, 400)
            return
        if repos_section:
            scan_dirs = repos_section.get("scan_dirs")
            if scan_dirs is not None and not isinstance(scan_dirs, list):
                self.send_json({"error": "repos.scan_dirs must be an array"}, 400)
                return
            skip_patterns = repos_section.get("skip_patterns")
            if skip_patterns is not None and not isinstance(skip_patterns, list):
                self.send_json({"error": "repos.skip_patterns must be an array"}, 400)
                return
            broad_scan = repos_section.get("broad_scan")
            if broad_scan is not None and not isinstance(broad_scan, dict):
                self.send_json({"error": "repos.broad_scan must be an object"}, 400)
                return
        goal_section = config.get("goal")
        if goal_section is not None and not isinstance(goal_section, dict):
            self.send_json({"error": "goal must be an object"}, 400)
            return
        # Security: validate all paths resolve under home directory
        scan_dirs = config.get("repos", {}).get("scan_dirs", [])
        invalid_dirs = [d for d in scan_dirs if not isinstance(d, str) or not _is_safe_path(d)]
        if invalid_dirs:
            print(f"  Config rejected: invalid scan_dirs: {invalid_dirs}")
            self.send_json({"error": "One or more scan directories are invalid"}, 400)
            return
        broad_root = config.get("repos", {}).get("broad_scan", {}).get("root")
        if broad_root and not _is_safe_path(broad_root):
            print(f"  Config rejected: invalid broad_scan root: {broad_root}")
            self.send_json({"error": "Invalid broad scan root directory"}, 400)
            return
        config_file = PROJECT_DIR / "config.json"
        with open(config_file, "w") as f:
            json.dump(config, f, indent=2)
        self.send_json({"status": "saved"})

    def handle_repos_discover(self, query_string):
        params = parse_qs(query_string)
        root = params.get("root", ["~/Developer"])[0]
        root = os.path.expanduser(root)
        try:
            max_depth = min(int(params.get("max_depth", ["4"])[0]), 6)
        except ValueError:
            max_depth = 4
        if not _is_safe_path(root):
            self.send_json({"error": "Invalid path"}, 400)
            return
        root = str(Path(root).resolve())
        if not os.path.isdir(root):
            self.send_json({"error": "Directory not found"}, 404)
            return
        try:
            result = subprocess.run(
                ["find", root, "-maxdepth", str(max_depth), "-name", ".git", "-type", "d"],
                capture_output=True, text=True, timeout=10,
            )
            repos = []
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if line and line.endswith("/.git"):
                    repo_path = line[:-5]  # remove /.git
                    repos.append({"path": repo_path, "name": os.path.basename(repo_path)})
            repos.sort(key=lambda r: r["name"].lower())
            self.send_json({"repos": repos})
        except subprocess.TimeoutExpired:
            self.send_json({"error": "Discovery timed out"}, 504)
        except Exception as e:
            print(f"  Repo discovery error: {e}")
            self.send_json({"error": "Discovery failed"}, 500)

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
    bind = "0.0.0.0" if "--bind-all" in sys.argv else "127.0.0.1"
    server = http.server.HTTPServer((bind, PORT), Handler)
    print(f"Singing Clock server running at http://{bind}:{PORT}")
    print(f"Press Ctrl+C to stop\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
