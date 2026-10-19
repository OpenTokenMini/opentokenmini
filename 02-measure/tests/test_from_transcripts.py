"""from-transcripts.py: thin usage.json builder over the readers keeps the old output shape (00-docs/demo)."""
import json, os, subprocess, sys, tempfile, unittest

import pathlib  # numbered stage dirs aren't importable: find the repo, use 02-measure/ for imports
REPO = str(next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir()))
MEASURE = os.path.join(REPO, "02-measure")
FIX = os.path.join(MEASURE, "tests", "fixtures", "readers")


class FromTranscripts(unittest.TestCase):
    def test_shape(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, "config.json")
            with open(cfg, "w") as f:  # only the fixture harnesses, nothing from $HOME
                json.dump({"readers": {"enabled": ["claude-code", "codex", "pi"],
                                       "paths": {"claude-code": FIX + "/claude", "codex": FIX + "/codex", "pi": FIX + "/pi"}}}, f)
            r = subprocess.run([sys.executable, os.path.join(MEASURE, "from-transcripts.py"), "100000"], capture_output=True,
                               text=True, env={**os.environ, "OTM_CONFIG": cfg, "OTM_DATA_DIR": d})
        self.assertEqual(r.returncode, 0, r.stderr)
        u = json.loads(r.stdout)
        self.assertEqual(set(u), {"generated", "days", "prices", "totals", "harnesses", "tokens", "by_day", "models",
                                  "projects", "tools", "sessions"})
        self.assertEqual(set(u["harnesses"]), {"claude-code", "codex", "pi"})
        self.assertGreater(u["totals"]["calls"], 0)
        self.assertNotIn("LEAKCANARY", r.stdout)


if __name__ == "__main__":
    unittest.main()
