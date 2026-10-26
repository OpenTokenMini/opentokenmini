"""deployments: fake gh over fixtures (no network); checks the METHOD.md worked example (D-ex)."""
import importlib.util, json, os, subprocess, sys, tempfile, unittest

import pathlib  # numbered stage dirs aren't importable: find the repo, use 02-measure/ for imports
REPO = str(next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir()))
sys.path.insert(0, os.path.join(REPO, "02-measure"))
from schemas.check import check_file

FIX = os.path.join(REPO, "04-auto-analysis", "tests", "fixtures", "deployments")
SCHEMA = "deployment"  # 02-measure/schemas/deployment.schema.json
ENTRY = os.path.join(REPO, "04-auto-analysis", "deployments", "deployments.py")
_spec = importlib.util.spec_from_file_location("deployments_main", ENTRY)
dep = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dep)


def load(name):
    with open(os.path.join(FIX, name)) as f:
        return json.load(f)


class FakeGh:
    """Stands in for gh(args, cwd): run list -> runs.json, run view ID -> jobs-ID.json; records calls."""
    def __init__(self):
        self.calls = []

    def __call__(self, args, cwd=None):
        self.calls.append((args, cwd))
        if args[:2] == ["run", "list"]:
            return load("runs.json")
        if args[:2] == ["run", "view"]:
            return load(f"jobs-{args[2]}.json")
        raise AssertionError(args)


class Deployments(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "app")  # local path -> repo_label "app", same as impact
        os.mkdir(self.repo)
        with open(os.path.join(FIX, "impact.jsonl")) as f:
            self.impact = [json.loads(l) for l in f if l.strip()]
        self.since = dep.ts("2026-10-01T00:00:00Z")
        self.gh = FakeGh()
        self.recs, self.errors = dep.run([self.repo], self.impact, self.since, gh_run=self.gh)
        self.by = {r["run_id"]: r for r in self.recs}

    def tearDown(self):
        self.tmp.cleanup()

    def test_scan(self):  # D-scan: run 99 is before since; in-progress run has no conclusion or duration
        self.assertEqual(self.errors, [])
        self.assertEqual(sorted(self.by), ["101", "102", "103", "104", "105"])
        self.assertEqual(self.by["101"]["duration_s"], 150)
        self.assertEqual(self.by["101"]["repo_label"], "app")
        self.assertIsNone(self.by["105"]["conclusion"])
        self.assertIsNone(self.by["105"]["duration_s"])
        args, cwd = self.gh.calls[0]
        self.assertEqual(cwd, os.path.realpath(self.repo))
        self.assertIn(">=2026-10-01", args)

    def test_join(self):  # D-join: exact sha, prefix sha, pending record ignored, other repo ignored
        self.assertEqual((self.by["101"]["session_id"], self.by["101"]["link"], self.by["101"]["link_p"]),
                         ("s-a", "trailer", 1.0))
        self.assertEqual((self.by["102"]["session_id"], self.by["102"]["harness"]), ("s-b", "codex"))
        for rid in ("103", "104", "105"):
            self.assertIsNone(self.by[rid]["session_id"])

    def test_failed_step(self):  # D-failed-step: first failed step of first failed job; job name when no step failed
        self.assertEqual(self.by["102"]["failed_step"], "test / unittest")
        self.assertEqual(self.by["103"]["failed_step"], "test")
        self.assertIsNone(self.by["101"]["failed_step"])
        views = [a for a, _ in self.gh.calls if a[:2] == ["run", "view"]]
        self.assertEqual(len(views), 2)

    def test_failed_detail_cap(self):  # D-failed-step: at most MAX_FAILED_DETAIL view calls per repo
        old, dep.MAX_FAILED_DETAIL = dep.MAX_FAILED_DETAIL, 1
        try:
            gh = FakeGh()
            recs, _ = dep.run([self.repo], self.impact, self.since, gh_run=gh)
        finally:
            dep.MAX_FAILED_DETAIL = old
        self.assertEqual(sum(1 for a, _ in gh.calls if a[:2] == ["run", "view"]), 1)
        self.assertIsNone({r["run_id"]: r for r in recs}["103"]["failed_step"])

    def test_rates(self):  # D-rate: agent 101 ok + 102 fail; baseline 103 fail + 104 ok; 105 not completed
        self.assertEqual(dep.rates(self.recs), {"agent": (0.5, 2), "baseline": (0.5, 2)})

    def test_remote_repo_and_errors(self):  # D-repo: OWNER/NAME uses -R and label NAME; a failing repo is skipped
        cwd, sel, label = dep.target("acme/widgets")
        self.assertEqual((cwd, sel, label), (None, ["-R", "acme/widgets"], "widgets"))

        def broken(args, cwd=None):
            raise RuntimeError("gh run: not logged in")
        recs, errors = dep.run(["acme/widgets"], self.impact, self.since, gh_run=broken)
        self.assertEqual(recs, [])
        self.assertEqual(len(errors), 1)
        recs, errors = dep.run([self.repo], self.impact, self.since, ci="gitlab_ci", gh_run=self.gh)
        self.assertEqual((recs, len(errors)), ([], 1))

    def test_records_valid(self):  # schema conventions: v=1, ISO UTC, sha pattern, impact link fields
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "deployments.jsonl")
            with open(path, "w") as f:
                f.writelines(json.dumps(r) + "\n" for r in self.recs)
            self.assertEqual(check_file(path, SCHEMA), [])

    def test_cli_help(self):  # entry point imports and parses without gh or network
        p = subprocess.run([sys.executable, ENTRY, "--help"], capture_output=True, text=True, cwd=REPO)
        self.assertEqual(p.returncode, 0, p.stderr)


if __name__ == "__main__":
    unittest.main()
