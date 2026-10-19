"""Collector sinks: name -> write(record: dict, cfg) -> None. Picked by config collector.sink."""
import json, os, sys, threading, urllib.request

FORWARD_ENV = "OTM_FORWARD_URL"  # forward_otlp: upstream base URL, e.g. http://host:4318
FORWARD_TIMEOUT_S = 5
_lock = threading.Lock()


def files(record, cfg):
    """N-raw-file: append to <data>/otel/<signal>-<UTC day of recv_ts>.jsonl."""
    d = os.path.join(cfg["data_dir"], "otel")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{record['path'].rsplit('/', 1)[-1]}-{record['recv_ts'][:10]}.jsonl")
    line = json.dumps(record, separators=(",", ":")) + "\n"
    with _lock, open(path, "a") as f:
        f.write(line)


def stdout(record, cfg):
    with _lock:
        sys.stdout.write(json.dumps(record, separators=(",", ":")) + "\n")
        sys.stdout.flush()


def forward_otlp(record, cfg):
    """Re-send the (redacted, hashed) OTLP JSON to another collector. Undecoded bodies are dropped."""
    base = os.environ.get(FORWARD_ENV)
    if not base:
        raise RuntimeError(f"forward_otlp needs ${FORWARD_ENV}")
    if "data" not in record:
        return
    req = urllib.request.Request(base.rstrip("/") + record["path"], json.dumps(record["data"]).encode(),
                                 {"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=FORWARD_TIMEOUT_S).read()


SINKS = {"files": files, "stdout": stdout, "forward_otlp": forward_otlp}
