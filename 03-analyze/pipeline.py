"""Run the batch stages in flow order, each as a subprocess; stop at the first nonzero exit.

Usage: python3 03-analyze/pipeline.py [--days N] [--from STAGE | --only STAGE] [--dry-run]
Stages: normalize readers analyze impact decide impact2 (impact2 = impact again, applies commit_link answers).
Data dir and config come from the env each stage already reads ($OTM_DATA_DIR, $OTM_CONFIG, 01-deploy/config.json).
normalize turns raw OTel (otel/) into events/otel.jsonl; analyze dedups it against transcripts (M-dedup).
The collector (long-running) is not part of this; run it as in README.md.
"""
import argparse, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo: <repo>/03-analyze/pipeline.py
DAYS = 30
# name, script, takes --days, main output (relative to the data dir)
STAGES = [
    ("normalize", "02-measure/collector/normalize.py", True, "events/otel.jsonl"),
    ("readers", "02-measure/readers/readers.py", True, "events/transcript.jsonl"),
    ("analyze", "03-analyze/analyze/analyze.py", True, "analysis.json"),
    ("impact", "04-auto-analysis/impact/impact.py", True, "impact_summary.json"),
    ("decide", "06-optional/decide/decide.py", False, "decisions.jsonl"),
    ("impact2", "04-auto-analysis/impact/impact.py", True, "impact_summary.json"),
]
NAMES = [s[0] for s in STAGES]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=float, default=DAYS)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--from", dest="start", choices=NAMES, help="start at this stage")
    g.add_argument("--only", choices=NAMES, help="run just this stage")
    ap.add_argument("--dry-run", action="store_true", help="print the commands, run nothing")
    a = ap.parse_args(argv)
    i = NAMES.index(a.only or a.start or NAMES[0])
    todo = STAGES[i:i + 1] if a.only else STAGES[i:]
    sys.path.insert(0, os.path.join(ROOT, "02-measure"))
    from schemas.config import load_config, data_dir
    data = data_dir(load_config(None))
    for name, script, days, out in todo:
        cmd = [sys.executable, os.path.join(ROOT, script)] + (["--days", str(a.days)] if days else [])
        if a.dry_run:
            print(" ".join(cmd))
            continue
        t = time.time()
        code = subprocess.run(cmd, cwd=ROOT).returncode
        print(f"{name:8} {time.time() - t:6.1f}s  exit {code}  {os.path.join(data, out)}", flush=True)
        if code:
            return code
    return 0


if __name__ == "__main__":
    sys.exit(main())
