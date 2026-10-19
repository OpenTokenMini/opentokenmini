import json, os, subprocess, sys, tempfile, unittest

import pathlib  # numbered stage dirs aren't importable: find the repo, use 02-measure/ for imports
REPO = str(next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir()))
MEASURE = os.path.join(REPO, "02-measure")
FIX = os.path.join(MEASURE, "tests", "fixtures", "readers")
PIPE = os.path.join(REPO, "03-analyze", "pipeline.py")


def run(env, *args):
    return subprocess.run([sys.executable, PIPE, *args], env=env, capture_output=True, text=True, timeout=120)


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.data = os.path.join(d, "data")
        cfg = {"data_dir": self.data,
               "readers": {"enabled": ["claude-code", "codex", "pi"],
                           "paths": {"claude-code": FIX + "/claude", "codex": FIX + "/codex", "pi": FIX + "/pi"}},
               "decide": {"vendor": "stub", "points": ["outlier_explanation", "recommendation"]}}
        path = os.path.join(d, "config.json")
        with open(path, "w") as f:
            json.dump(cfg, f)
        self.env = {k: v for k, v in os.environ.items() if k not in ("OTM_DATA_DIR", "OTM_LEDGER")}
        self.env["OTM_CONFIG"] = path

    def tearDown(self):
        self.tmp.cleanup()

    def test_dry_run(self):
        r = run(self.env, "--dry-run", "--days", "7")
        lines = r.stdout.splitlines()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(lines), 6)
        self.assertIn("collector/normalize.py --days 7", lines[0])
        self.assertIn("readers/readers.py --days 7", lines[1])
        self.assertTrue(lines[4].endswith("decide/decide.py"))
        self.assertFalse(os.path.exists(self.data))
        self.assertEqual(len(run(self.env, "--dry-run", "--from", "decide").stdout.splitlines()), 2)
        self.assertEqual(len(run(self.env, "--dry-run", "--only", "analyze").stdout.splitlines()), 1)

    def test_fixture_run(self):
        r = run(self.env, "--days", "3650")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        summary = [l for l in r.stdout.splitlines() if " exit " in l]
        self.assertEqual([l.split()[0] for l in summary], ["normalize", "readers", "analyze", "impact", "decide", "impact2"])
        for f in ("events/otel.jsonl", "events/transcript.jsonl", "analysis.json", "sessions.jsonl", "impact_summary.json"):
            self.assertTrue(os.path.exists(os.path.join(self.data, f)), f)

    def test_stops_on_failure(self):  # unknown vendor: decide exits nonzero, impact2 never runs
        path = self.env["OTM_CONFIG"]
        with open(path) as f:
            cfg = json.load(f)
        cfg["decide"]["vendor"] = "nope"
        with open(path, "w") as f:
            json.dump(cfg, f)
        r = run(self.env, "--from", "decide")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual([l.split()[0] for l in r.stdout.splitlines() if " exit " in l], ["decide"])


if __name__ == "__main__":
    unittest.main()
