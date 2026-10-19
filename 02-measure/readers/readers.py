#!/usr/bin/env python3
"""Transcript readers: local session logs of each harness -> events (source "transcript").
Usage: python3 02-measure/readers/readers.py [--days N] [--harness ID] [--config PATH] [--out DIR]
Writes <data dir>/events/transcript.jsonl and prints a per-harness summary (JSON) on stdout. Specs: readers/METHOD.md."""
import argparse, json, os, sys
from datetime import datetime, timedelta, timezone

import pathlib  # numbered stage dirs aren't importable: find the repo, put 02-measure/ on sys.path
REPO = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir())
sys.path.insert(0, str(REPO / "02-measure"))
from schemas.config import load_config, data_dir, connector
import antigravity, claude_code, codex, opencode, pi

DAYS = 30
OUT_FILE = os.path.join("events", "transcript.jsonl")
READERS = {"claude-code": claude_code.read, "codex": codex.read, "antigravity": antigravity.read,
           "opencode": opencode.read, "pi": pi.read}  # harness id -> read(since: datetime, cfg) -> Iterable[event]


def run(harnesses, since, cfg):
    """R-isolate: one reader failing (format change) is reported and does not stop the others."""
    events, summary = [], {}
    for h in harnesses:
        s = summary[h] = {"events": 0, "calls": 0, "cost": 0.0, "unpriced_calls": 0, "error": None}
        try:
            got = list(connector(READERS, h, "readers.enabled")(since, cfg))
        except Exception as e:
            s["error"] = f"{type(e).__name__}: {e}"
            continue
        for e in got:
            if e["kind"] == "api_call":
                s["calls"] += 1
                s["cost"] += e["cost"]["total"]
                s["unpriced_calls"] += e["cost_basis"] == "unknown"
        s["events"], s["cost"] = len(got), round(s["cost"], 4)
        events += got
    if antigravity.coverage and "antigravity" in summary:
        summary["antigravity"]["skipped"] = len(antigravity.coverage)
        summary["antigravity"]["error"] = summary["antigravity"]["error"] or next(iter(antigravity.coverage.values()))
    return events, summary


def write(events, harnesses, path):
    """R-output: rewrite the file; with --harness, lines of the other harnesses are kept."""
    keep = []
    if os.path.exists(path):
        with open(path) as f:
            keep = [l for l in f if json.loads(l).get("harness") not in harnesses]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.writelines(keep)
        for e in sorted(events, key=lambda e: (e["ts"], e["harness"], e["session_id"])):
            f.write(json.dumps(e) + "\n")
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=float, default=DAYS)
    ap.add_argument("--harness", action="append", help="harness id, repeatable (default: config readers.enabled)")
    ap.add_argument("--config")
    ap.add_argument("--out", help="data root to write into (default: data dir)")
    a = ap.parse_args()
    cfg = load_config(a.config)
    harnesses = a.harness or cfg["readers"]["enabled"]
    since = datetime.now(timezone.utc) - timedelta(days=a.days)
    events, summary = run(harnesses, since, cfg)
    out = os.path.join(os.path.abspath(os.path.expanduser(a.out)) if a.out else data_dir(cfg), OUT_FILE)
    write(events, set(harnesses), out)
    json.dump({"out": out, "since": since.strftime("%Y-%m-%dT%H:%M:%SZ"), "harnesses": summary}, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
