"""analyze connectors: name -> function, picked by config `analyze.source` / `analyze.sink`.
source: load_events(cfg) -> Iterable[event]    sink: write_outputs(sessions, analysis, cfg) -> None
Runtime paths are in cfg["analyze"]["_events_dir"] and cfg["analyze"]["_out_dir"] (set by analyze.py)."""
import glob, json, os, sys

EVENT_GLOB = "*.jsonl"
SESSIONS_FILE, ANALYSIS_FILE = "sessions.jsonl", "analysis.json"


def _lines(f, name):
    bad = 0
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except ValueError:
            bad += 1
    if bad:
        print(f"analyze: skipped {bad} unparsable lines in {name}", file=sys.stderr)


def files_source(cfg):
    """Every events/*.jsonl under the events dir (events/otel.jsonl, events/transcript.jsonl)."""
    for path in sorted(glob.glob(os.path.join(cfg["analyze"]["_events_dir"], EVENT_GLOB))):
        with open(path) as f:
            yield from _lines(f, path)


def stdin_source(cfg):
    yield from _lines(sys.stdin, "stdin")


def _atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def files_sink(sessions, analysis, cfg):
    out = cfg["analyze"]["_out_dir"]
    os.makedirs(out, exist_ok=True)
    _atomic(os.path.join(out, SESSIONS_FILE), "".join(json.dumps(s) + "\n" for s in sessions))
    _atomic(os.path.join(out, ANALYSIS_FILE), json.dumps(analysis, indent=1) + "\n")


def stdout_sink(sessions, analysis, cfg):
    print(json.dumps(analysis, indent=1))


SOURCES = {"files": files_source, "stdin": stdin_source}
SINKS = {"files": files_sink, "stdout": stdout_sink}
