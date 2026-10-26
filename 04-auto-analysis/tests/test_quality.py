"""quality: fixture transcripts (fixtures/quality/claude/) + a temp git repo; checks the METHOD.md worked example (Q-ex). No network."""
import importlib.util, json, os, subprocess, sys, tempfile, unittest
from datetime import datetime, timezone

import pathlib  # numbered stage dirs aren't importable: find the repo, use 02-measure/ for imports
REPO = str(next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir()))
sys.path.insert(0, os.path.join(REPO, "02-measure"))
from schemas.check import validate

FIX = os.path.join(REPO, "04-auto-analysis", "tests", "fixtures", "quality")
SCHEMA = os.path.join(FIX, "quality.schema.json")  # proposed record schema, see quality/AGENTS.md
ENTRY = os.path.join(REPO, "04-auto-analysis", "quality", "quality.py")
_spec = importlib.util.spec_from_file_location("quality_main", ENTRY)
quality = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(quality)

SINCE = datetime(2026, 9, 30, tzinfo=timezone.utc)


def commit(repo, path, when):
    with open(os.path.join(repo, path), "a") as f:
        f.write(when + "\n")
    env = dict(os.environ, GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@x")
    subprocess.run(["git", "-C", repo, "add", path], check=True)
    subprocess.run(["git", "-C", repo, "commit", "-qm", "c"], check=True, env=env)
    return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def link(sid, p, shas):
    return {"v": 1, "session_id": sid, "harness": "claude-code", "repo_label": "app", "link_p": p,
            "commits": [{"sha": s, "ts": t, "reverted_by": None} for s, t in shas]}


class Quality(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        repo = os.path.join(cls.tmp.name, "app")
        subprocess.run(["git", "init", "-q", repo], check=True)
        t1, t2 = "2026-10-01T10:15:00Z", "2026-10-01T10:28:00Z"
        cls.c1, cls.c2 = commit(repo, "a.py", t1), commit(repo, "b.py", t2)
        cls.c3 = commit(repo, "a.py", "2026-10-01T18:00:00Z")   # reworks c1 within REWORK_HOURS
        cls.c4 = commit(repo, "b.py", "2026-10-03T09:00:00Z")   # touches c2's file, but after REWORK_HOURS
        cls.sessions = quality.scan(os.path.join(FIX, "claude"), SINCE)
        impact = [link("s1", 1.0, [(cls.c1, t1), (cls.c2, t2)]), link("s2", None, [(cls.c4, "2026-10-03T09:00:00Z")])]
        cls.recs, cls.summary = quality.build(cls.sessions, impact, {"app": quality.git_log(repo, SINCE)})
        cls.by = {(r["kind"], r.get("sha") or r["session_id"]): r for r in cls.recs}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_schema(self):
        for r in self.recs:
            self.assertEqual(validate(r, SCHEMA), [], r)

    def test_session(self):  # Q-tool-error, Q-test, Q-risk, Q-rework-session
        s1, s2 = self.by["session", "s1"], self.by["session", "s2"]
        self.assertEqual((s1["tool_calls"], s1["tool_errors"], s1["tool_error_rate"]), (9, 1, 0.111111))
        self.assertEqual((s1["test_runs"], s1["test_failed"], s1["last_test"]), (2, 1, "pass"))
        self.assertEqual(s1["risky"], {"destructive": 1, "exfiltration": 1, "secrets": 1})
        self.assertEqual((s1["files_edited"], s1["files_reworked"]), (2, 1))
        self.assertEqual(s1["commits"], sorted([self.c1, self.c2]))
        self.assertEqual((s2["test_runs"], s2["test_failed"], s2["last_test"]), (1, 1, "fail"))
        self.assertEqual((s2["files_edited"], s2["files_reworked"], s2["commits"]), (2, 0, []))  # s2 pending: no commits
        self.assertEqual((s1["start"], s2["end"]), ("2026-10-01T10:00:00Z", "2026-10-03T09:00:01Z"))

    def test_commit(self):  # Q-test-last, Q-rework-commit; pending impact records give no commit record
        c1, c2 = self.by["commit", self.c1], self.by["commit", self.c2]
        self.assertEqual((c1["last_test"], c1["reworked_by"]), ("fail", [self.c3]))
        self.assertEqual((c2["last_test"], c2["reworked_by"]), ("pass", []))
        self.assertNotIn(("commit", self.c4), self.by)

    def test_summary(self):  # Q-summary
        s = self.summary
        self.assertEqual((s["sessions"], s["tool_calls"], s["tool_error_rate"]), (2, 12, 0.166667))
        self.assertEqual((s["sessions_with_tests"], s["test_runs"], s["test_fail_rate"]), (2, 3, 0.666667))
        self.assertEqual((s["file_rework_rate"], s["commits"], s["commit_rework_rate"]), (0.25, 2, 0.5))
        self.assertEqual((s["commits_last_test_fail"], s["commits_without_test"]), (1, 0))

    def test_unknown_commit(self):  # Q-rework-commit: a sha not in the scanned log gives reworked_by null
        recs, s = quality.build(self.sessions, [link("s1", 1.0, [("f" * 40, "2026-10-01T10:15:00Z")])], {})
        self.assertIsNone(next(r for r in recs if r["kind"] == "commit")["reworked_by"])
        self.assertIsNone(s["commit_rework_rate"])

    def test_cli(self):  # end to end through main(): writes both files into --out
        out = os.path.join(self.tmp.name, "out")
        env = dict(os.environ, OTM_DATA_DIR=os.path.join(self.tmp.name, "data"))
        p = subprocess.run([sys.executable, ENTRY, "--days", "100000", "--transcripts", os.path.join(FIX, "claude"),
                            "--out", out], capture_output=True, text=True, env=env, cwd=REPO)
        self.assertEqual(p.returncode, 0, p.stderr)
        with open(os.path.join(out, "quality_summary.json")) as f:
            self.assertEqual(json.load(f)["sessions"], 2)


if __name__ == "__main__":
    unittest.main()
