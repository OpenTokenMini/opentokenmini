#!/usr/bin/env python3
"""Dev helper: serve the dashboard with a data dir and log browser console events.

GET /            dashboard/index.html (response carries X-OTM-Dev, which turns on page telemetry)
GET /data/<f>    DATA_FILES only (raw events/otel carry emails and prompts), from the data dir (--data, else $OTM_DATA_DIR, else ~/.local/share/opentokenmini)
POST /console    one JSON event per request, appended to LOG
"""
import argparse, json, os, sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = 7840
LOG = "/tmp/otm-dashboard-console.jsonl"
MAX_EVENT = 8192  # bytes accepted per console event
BAD_SNIPPET = 200  # chars of an unparseable console body kept in LOG
DATA_PREFIX, CONSOLE_PATH = "/data/", "/console"
DATA_FILES = {"analysis.decided.json", "analysis.json", "impact_summary.json", "decisions.jsonl", "sessions.jsonl",
              "readout.json", "issues_summary.json"}  # what index.html reads (last two optional)
DATA_ENV, DEFAULT_DATA_DIR = "OTM_DATA_DIR", "~/.local/share/opentokenmini"
DEV_HEADERS = {"X-OTM-Dev": "1", "Cache-Control": "no-store"}
HERE = os.path.dirname(os.path.abspath(__file__))


def handler(data_dir, log=None):
    class H(SimpleHTTPRequestHandler):
        def translate_path(self, path):
            p = path.split("?", 1)[0]
            if p.startswith(DATA_PREFIX):
                return os.path.join(data_dir, p[len(DATA_PREFIX):])
            return super().translate_path(path)

        def send_head(self):
            p = self.path.split("?", 1)[0]
            if p.startswith(DATA_PREFIX) and p[len(DATA_PREFIX):] not in DATA_FILES:
                self.send_error(404)
                return None
            return super().send_head()

        def end_headers(self):
            for k, v in DEV_HEADERS.items():
                self.send_header(k, v)
            super().end_headers()

        def do_POST(self):
            if self.path != CONSOLE_PATH:
                return self.send_error(404)
            n = min(int(self.headers.get("Content-Length") or 0), MAX_EVENT)
            body = self.rfile.read(n).decode("utf-8", "replace")
            try:
                ev = json.loads(body)
            except ValueError:
                ev = {"kind": "bad", "msg": body[:BAD_SNIPPET]}
            with open(H.log, "a") as f:
                f.write(json.dumps(ev) + "\n")
            self.send_response(204)
            self.end_headers()

        def log_message(self, *a):
            pass

    H.log = log or LOG
    return lambda *a, **k: H(*a, directory=HERE, **k)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default=None, help="data dir served under /data/")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--log", default=None, help=f"console log file (default {LOG})")
    a = ap.parse_args()
    data_dir = os.path.abspath(os.path.expanduser(a.data or os.environ.get(DATA_ENV) or DEFAULT_DATA_DIR))
    srv = ThreadingHTTPServer((HOST, a.port), handler(data_dir, a.log))
    print(f"http://{HOST}:{a.port}/  data={data_dir}  log={a.log or LOG}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    sys.exit(main())
