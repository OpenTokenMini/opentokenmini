#!/usr/bin/env python3
"""Serve the dashboard mockup; POST /console appends browser errors/warnings to LOG."""
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST, PORT = "127.0.0.1", 7844
LOG = "/tmp/otm-dashboards-console.jsonl"
MAX_EVENT = 8192  # bytes accepted per console event
HERE = str(Path(__file__).parent)


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=HERE, **k)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_POST(self):
        if self.path != "/console":
            return self.send_error(404)
        body = self.rfile.read(min(int(self.headers.get("Content-Length") or 0), MAX_EVENT))
        with open(LOG, "a") as f:
            f.write(body.decode("utf-8", "replace").replace("\n", " ") + "\n")
        self.send_response(204)
        self.end_headers()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"http://{HOST}:{PORT}/  log={LOG}", flush=True)
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()
