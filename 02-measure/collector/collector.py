#!/usr/bin/env python3
"""OTLP/HTTP receiver: POST /v1/logs|metrics|traces -> one raw record per request (schemas/raw.schema.json).

JSON bodies are stored as OTLP JSON; protobuf bodies are decoded with the optional `opentelemetry-proto`
package if importable, else logs/traces with the stdlib protowire.py (N-pb); anything else is stored as an `undecoded` summary (N-undecoded).
Content attributes are redacted (N-redact), identity attributes hashed (N-identity), emails hashed and /home/<user> -> ~ in every string (N-pii). Sink = connector from collector/connectors.py (config collector.sink).
Run from the repo root: python3 02-measure/collector/collector.py [--config PATH] [--out DATA_ROOT]
"""
import argparse, base64, hashlib, importlib.util, json, os, re, sys, time, zlib
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pathlib  # numbered stage dirs aren't importable: find the repo, put 02-measure/ on sys.path
REPO = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir())
sys.path.insert(0, str(REPO / "02-measure"))
from schemas.config import load_config, data_dir, connector


def _load(name):  # by path, unique module name: every stage has a connectors.py
    spec = importlib.util.spec_from_file_location("collector_" + name, os.path.join(os.path.dirname(os.path.abspath(__file__)), name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


connectors, protowire = _load("connectors"), _load("protowire")
SINKS = connectors.SINKS

PORT = int(os.environ.get("OTM_PORT", 6979))  # config collector.port overrides; null = this
MAX_BODY = 32 * 1024 * 1024  # N-body-limit: bytes, before and after gzip
HASH_LEN = 12  # N-identity: hex chars of sha256 kept
SIGNALS = ("logs", "metrics", "traces")
KEEP_RAW_UNDECODED = False  # N-undecoded: True also stores the unredacted body as data_b64 (may hold prompt text)
# N-redact: attribute keys whose values are prompt/response content; value replaced by its length
REDACT = re.compile(r"^(prompt|prompt_text|user_prompt|ai\.prompt.*|ai\.response\.(text|toolCalls|object|reasoning.*)|"
                    r"ai\.toolCall\.(args|result)|gen_ai\.(prompt|completion|input\.messages|output\.messages|system_instructions).*|"
                    r"tool_(input|output|result|parameters)|.*\.content)$")
# N-identity: attribute keys whose string values are hashed when collector.hash_identity is true
IDENTITY = {"user.email", "user.id", "user.account_id", "user.account_uuid", "organization.id",
            "ai.telemetry.metadata.userId", "enduser.id", "host.name"}
HEX12 = re.compile(r"^[0-9a-f]{%d}$" % HASH_LEN)
# N-pii: applied always (hash_identity does not switch it off), at write time, to every string value
PII_KEYS = {"user.email", "user.account_uuid"}  # whole value -> hash_id
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")  # each match inside any string -> hash_id
HOME = re.compile(r"/home/[^/\s\"':]+")  # /home/<user> -> ~
SALT_ENV = "OTM_ID_SALT"  # N-identity salt: sha256(salt + value); unset/empty = plain sha256 (joins with older hashes). normalize.py reads the same var
SALT = os.environ.get(SALT_ENV, "")

try:
    from google.protobuf.json_format import MessageToDict
    from opentelemetry.proto.collector.logs.v1 import logs_service_pb2 as L
    from opentelemetry.proto.collector.metrics.v1 import metrics_service_pb2 as M
    from opentelemetry.proto.collector.trace.v1 import trace_service_pb2 as T
    PB = {"logs": L.ExportLogsServiceRequest, "metrics": M.ExportMetricsServiceRequest,
          "traces": T.ExportTraceServiceRequest}
except ImportError:
    PB = {}


def hash_id(v):
    """N-identity: sha256(value)[:HASH_LEN]; already-hashed values are kept."""
    v = str(v)
    return v if HEX12.match(v) else hashlib.sha256((SALT + v).encode()).hexdigest()[:HASH_LEN]


def pii(s):
    """N-pii: emails -> hash_id, /home/<user> -> ~ inside one string."""
    return HOME.sub("~", EMAIL.sub(lambda m: hash_id(m.group()), s))


def scrub(o, hash_identity=True):
    """N-redact + N-identity + N-pii, in place, on every OTLP {key, value} attribute at any depth."""
    if isinstance(o, dict):
        k, v = o.get("key"), o.get("value")
        if isinstance(k, str) and isinstance(v, dict):
            if REDACT.match(k):
                o["value"] = {"stringValue": f"[redacted len={len(json.dumps(v))}]"}
                return
            if v.get("stringValue") and (k in PII_KEYS or (hash_identity and k in IDENTITY)):
                o["value"] = {"stringValue": hash_id(v["stringValue"])}
                return
        for kk, x in o.items():
            if isinstance(x, str) and kk != "key":
                o[kk] = pii(x)
            else:
                scrub(x, hash_identity)
    elif isinstance(o, list):
        for i, x in enumerate(o):
            if isinstance(x, str):
                o[i] = pii(x)
            else:
                scrub(x, hash_identity)


def hex_ids(o):
    """Protobuf JSON encodes ids as base64; OTLP JSON uses hex."""
    if isinstance(o, dict):
        for k, v in o.items():
            if k in ("traceId", "spanId", "parentSpanId") and isinstance(v, str) and v:
                o[k] = base64.b64decode(v).hex()
            else:
                hex_ids(v)
    elif isinstance(o, list):
        for v in o:
            hex_ids(v)


def service_name(data):
    for res in next((v for k, v in data.items() if k.startswith("resource")), None) or []:
        for a in res.get("resource", {}).get("attributes", []):
            if a.get("key") == "service.name":
                return a.get("value", {}).get("stringValue")
    return None


def unzip(body):
    """gzip/deflate with the N-body-limit applied to the output; None if over the limit."""
    d = zlib.decompressobj(47)  # 32+15: auto-detect gzip or zlib header
    out = d.decompress(body, MAX_BODY + 1)
    return None if len(out) > MAX_BODY or d.unconsumed_tail else out


def make_record(path, ctype, body, hash_identity=True, warn=lambda m: None):
    """Raw record (schemas raw v1) from one decoded request body."""
    signal = path.rsplit("/", 1)[-1]
    rec = {"v": 1, "recv_ts": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
           "path": path, "content_type": ctype, "harness_hint": None}
    data = None
    if "protobuf" in ctype and signal in PB:
        req = PB[signal]()
        req.ParseFromString(body)
        data = MessageToDict(req)
        hex_ids(data)
    elif "protobuf" in ctype and signal in protowire.REQUEST:
        data = protowire.decode(body, protowire.REQUEST[signal])
    elif "protobuf" not in ctype:
        try:
            data = json.loads(body)
        except ValueError:
            data = None
    if isinstance(data, dict):
        scrub(data, hash_identity)
        rec["harness_hint"], rec["data"] = service_name(data), data
    elif KEEP_RAW_UNDECODED:  # N-undecoded opt-in: body kept as-is (not redacted), warned once per process
        warn(f"storing undecoded {ctype or 'unknown'} body as data_b64 (not redacted)")
        rec["data_b64"] = base64.b64encode(body).decode()
    else:  # N-undecoded: body dropped, only a summary kept
        reason = "no_protobuf_decoder" if "protobuf" in ctype else "not_json_object"
        warn(f"dropping undecoded {ctype or 'unknown'} body ({reason})")
        rec["undecoded"] = {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(), "content_type": ctype, "reason": reason}
    return rec


def make_handler(cfg, sink):
    token = os.environ.get(cfg["collector"]["token_env"] or "", "") if cfg["collector"]["token_env"] else ""
    hash_identity = cfg["collector"]["hash_identity"]
    warned = set()

    def warn(msg):
        if msg not in warned:
            warned.add(msg)
            sys.stderr.write(f"{time.strftime('%H:%M:%S')} WARN {msg}\n")

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            path = "/" + self.path.split("?")[0].strip("/")
            if path not in tuple(f"/v1/{s}" for s in SIGNALS):
                return self._send(404, b'{"error":"use /v1/logs|metrics|traces"}')
            if token and self.headers.get("Authorization", "") != f"Bearer {token}":
                return self._send(401, b'{"error":"bearer token required"}')
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                return self._send(413, b'{"error":"body too large"}')
            body = self.rfile.read(n)
            if self.headers.get("Content-Encoding", "") in ("gzip", "deflate"):
                try:
                    body = unzip(body)
                except zlib.error:
                    return self._send(400, b'{"error":"bad gzip"}')
                if body is None:
                    return self._send(413, b'{"error":"body too large"}')
            ctype = self.headers.get("Content-Type", "").split(";")[0].strip()
            try:
                rec = make_record(path, ctype, body, hash_identity, warn)
            except Exception as e:
                return self._send(400, json.dumps({"error": repr(e)[:200]}).encode())
            try:
                sink(rec, cfg)
            except Exception as e:
                warn(f"sink {cfg['collector']['sink']} failed: {e!r}"[:200])
                return self._send(500, b'{"error":"sink failed"}')
            if "protobuf" in ctype:  # empty Export*ServiceResponse = zero bytes
                return self._send(200, b"", "application/x-protobuf")
            self._send(200, b"{}")

        def do_GET(self):
            if self.path.split("?")[0].rstrip("/") == "/health":
                return self._send(200, json.dumps({"ok": True, "protobuf": "lib" if PB else "stdlib logs/traces", "auth": bool(token),
                                                   "sink": cfg["collector"]["sink"]}).encode())
            self._send(404, b'{"error":"GET /health only"}')

        def _send(self, code, body, ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *a):
            sys.stderr.write("%s %s\n" % (time.strftime("%H:%M:%S"), fmt % a))

    return H


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config")
    ap.add_argument("--out", help="data root (default: OTM_DATA_DIR > config data_dir > ~/.local/share/opentokenmini)")
    a = ap.parse_args()
    cfg = load_config(a.config)
    if a.out:
        cfg["data_dir"] = a.out
        os.environ.pop("OTM_DATA_DIR", None)
    cfg["data_dir"] = data_dir(cfg)
    c = cfg["collector"]
    sink = connector(SINKS, c["sink"], "collector.sink")
    port = c["port"] if c["port"] is not None else PORT
    srv = ThreadingHTTPServer((c["bind"], port), make_handler(cfg, sink))
    print(f"listening {c['bind']}:{port} sink={c['sink']} data={cfg['data_dir']} protobuf={'lib' if PB else 'stdlib logs/traces'}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
