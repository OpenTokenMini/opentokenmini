#!/usr/bin/env python3
"""Telemetry coverage (N-coverage in collector/METHOD.md): Claude Code requests in local transcripts vs api_request
records the collector stored, last N hours, joined on request_id. Estimates the share of requests telemetry misses.
Reads the collector's raw files read-only; prints JSON. Usage: python3 02-measure/coverage.py [hours] [--data DIR]"""
import argparse, glob, json, os, sys
from datetime import datetime, timedelta, timezone

import pathlib  # numbered stage dirs aren't importable: find the repo, put 02-measure/ on sys.path
REPO = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir())
sys.path[:0] = [str(REPO / "02-measure" / "readers"), str(REPO / "02-measure")]
import claude_code  # noqa: E402
from schemas.config import load_config, data_dir  # noqa: E402

HOURS = 24
HARNESS = "claude-code"  # service.name
EVENT = "api_request"  # OTel event.name of one successful API call
TOP_SESSIONS = 5  # sessions with the most missing requests listed in the output


def attrs(lst):
    return {a["key"]: next(iter(a.get("value", {}).values()), None) for a in lst or []}


def otel_requests(raw_dir, since):
    """request_id -> session_id from api_request log records of HARNESS with timestamp >= since."""
    out, days = {}, {(since + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((datetime.now(timezone.utc) - since).days + 2)}
    for path in glob.glob(os.path.join(raw_dir, "logs-*.jsonl")):
        if path[-16:-6] not in days:
            continue
        with open(path, errors="replace") as f:
            for line in f:
                if EVENT not in line:
                    continue
                try:
                    data = json.loads(line).get("data") or {}
                except ValueError:
                    continue
                for rl in data.get("resourceLogs", []):
                    if attrs(rl.get("resource", {}).get("attributes")).get("service.name") != HARNESS:
                        continue
                    for sl in rl.get("scopeLogs", []):
                        for lr in sl.get("logRecords", []):
                            a = attrs(lr.get("attributes"))
                            ts = int(lr.get("timeUnixNano") or 0) / 1e9
                            if a.get("event.name") == EVENT and a.get("request_id") and ts >= since.timestamp():
                                out[a["request_id"]] = a.get("session.id")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("hours", nargs="?", type=float, default=HOURS)
    ap.add_argument("--data", help="collector data root (default: OTM_DATA_DIR > config data_dir > ~/.local/share/opentokenmini)")
    a = ap.parse_args()
    cfg = load_config(None)
    since = datetime.now(timezone.utc) - timedelta(hours=a.hours)
    otel = otel_requests(os.path.join(a.data or data_dir(cfg), "otel"), since)
    tr = {e["request_id"]: e["session_id"] for e in claude_code.read(since, cfg)
          if e["kind"] == "api_call" and e["request_id"] and e["error"] != "api_error"}
    missing = [r for r in tr if r not in otel]
    by_sess = {}
    for r in missing:
        by_sess[tr[r]] = by_sess.get(tr[r], 0) + 1
    sessions = set(tr.values())
    covered = {tr[r] for r in tr if r in otel}
    print(json.dumps({"hours": a.hours, "transcript_requests": len(tr), "otel_requests": len(otel),
                      "matched": len(tr) - len(missing), "missing": len(missing),
                      "missing_pct": round(100 * len(missing) / len(tr), 1) if tr else None,
                      "otel_only": sum(r not in tr for r in otel),  # other machines, or transcripts already gone
                      "sessions": len(sessions), "sessions_without_telemetry": len(sessions - covered),
                      "top_missing_sessions": sorted(by_sess.items(), key=lambda x: -x[1])[:TOP_SESSIONS]}, indent=1))


if __name__ == "__main__":
    main()
