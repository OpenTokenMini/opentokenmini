import importlib.util, json, unittest.mock, os, shutil, subprocess, sys, tempfile, unittest

import pathlib  # numbered stage dirs aren't importable: find the repo, use 02-measure/ for imports
REPO = str(next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir()))
MEASURE = os.path.join(REPO, "02-measure")
FIX = os.path.join(MEASURE, "tests", "fixtures", "readers")
PIPE = os.path.join(REPO, "03-analyze", "pipeline.py")
NET = os.path.join(REPO, "03-analyze", "tests", "fixtures", "pipeline")  # fake gh + gh.json, impact/sessions for network stages
AUTO = os.path.join(REPO, "04-auto-analysis", "tests", "fixtures")  # quality/ and mcp_usage/ transcripts for the local stages


def fake_gh_bin(root):
    """A bin dir whose gh is fixtures/pipeline/fake_gh.py; put first on PATH so no test reaches the real gh."""
    b = os.path.join(root, "bin")
    os.makedirs(b)
    with open(os.path.join(b, "gh"), "w") as f:
        f.write(f'#!/bin/sh\nexec "{sys.executable}" "{os.path.join(NET, "fake_gh.py")}" "$@"\n')
    os.chmod(os.path.join(b, "gh"), 0o755)
    return b


def pipeline():
    spec = importlib.util.spec_from_file_location("pipeline", PIPE)
    pipe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipe)
    return pipe


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
        self.env["HOME"] = d  # mcp reads ~/.claude.json: none here
        self.env["PATH"] = fake_gh_bin(d) + os.pathsep + self.env["PATH"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_dry_run(self):
        r = run(self.env, "--dry-run", "--days", "7")
        lines = r.stdout.splitlines()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(lines), 13)
        self.assertIn("collector/normalize.py --days 7", lines[0])
        self.assertIn("readers/readers.py --days 7", lines[1])
        self.assertTrue(lines[4].endswith("decide/decide.py"))
        self.assertIn("quality/quality.py --days 7", lines[6])
        self.assertIn("mcp-usage/mcp_usage.py --days 7", lines[7])
        self.assertIn("orchestration/orchestration.py --days 7", lines[8])
        self.assertIn("context/context.py --days 7", lines[9])
        self.assertIn("orch-ux/orch_ux.py --days 7", lines[10])
        self.assertEqual(lines[11:], ["# deployments skipped: no repos", "# issues   skipped: no repos"])
        self.assertFalse(os.path.exists(self.data))
        self.assertEqual(len(run(self.env, "--dry-run", "--from", "decide").stdout.splitlines()), 9)
        self.assertEqual(len(run(self.env, "--dry-run", "--only", "analyze").stdout.splitlines()), 1)

    def test_fixture_run(self):
        r = run(self.env, "--days", "3650")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        summary = [l for l in r.stdout.splitlines() if " exit " in l and "skipped:" not in l]
        self.assertEqual([l.split()[0] for l in summary],
                         ["normalize", "readers", "analyze", "impact", "decide", "impact2", "quality", "mcp", "orchestration", "context", "orch_ux"])
        for f in ("events/otel.jsonl", "events/transcript.jsonl", "analysis.json", "sessions.jsonl", "impact_summary.json"):
            self.assertTrue(os.path.exists(os.path.join(self.data, f)), f)
        self.assertIn("deployments skipped: no repos", r.stdout)  # fixture sessions' repos are not on this machine
        with open(os.path.join(self.data, "readout.json")) as f:
            ro = json.load(f)
        self.assertEqual((ro["deployments"], ro["issues"]), ({"skipped": "no repos"}, {"skipped": "no repos"}))
        # quality.py raises KeyError on these fixtures (a tool_result without tool_use_id): either outcome is a section
        self.assertTrue("risky" in ro["quality"] or ro["quality"]["skipped"].startswith("exit 1"), ro["quality"])
        self.assertEqual(set(ro["mcp"]), {"servers_used", "servers_called", "never_called", "mcp_ctx_share_of_tools"})
        self.assertIn("findings", ro["context"])
        self.assertIn("orchestration", ro)
        self.assertIn("verdict", ro["orch_ux"])

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


class NetworkStages(unittest.TestCase):
    """deployments + issues as pipeline stages: fake gh, seeded impact.jsonl/sessions.jsonl, a local clone 'app'. No network."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.data, self.repo, self.log = os.path.join(d, "data"), os.path.join(d, "app"), os.path.join(d, "gh.log")
        os.makedirs(self.data)
        os.makedirs(os.path.join(self.repo, "sub"))
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        subprocess.run(["git", "-C", self.repo, "remote", "add", "origin", "https://github.com/me/app.git"], check=True)
        shutil.copy(os.path.join(NET, "impact.jsonl"), self.data)
        with open(os.path.join(NET, "sessions.jsonl")) as f, open(os.path.join(self.data, "sessions.jsonl"), "w") as g:
            g.write(f.read().replace("{home}", "~").replace("{repo}", self.repo))  # sessions may store "~/app"
        self.cfg = os.path.join(d, "config.json")
        self.config({"data_dir": self.data})
        self.env = {k: v for k, v in os.environ.items() if k not in ("OTM_DATA_DIR", "OTM_LEDGER")}
        self.env.update(OTM_CONFIG=self.cfg, FAKE_GH_LOG=self.log, HOME=d, PATH=fake_gh_bin(d) + os.pathsep + os.environ["PATH"])

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, cfg):
        with open(self.cfg, "w") as f:
            json.dump(cfg, f)

    def readout(self):
        with open(os.path.join(self.data, "readout.json")) as f:
            return json.load(f)

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return f.read().splitlines()

    def test_runs_and_readout(self):  # repos derived from linked sessions: s-1 -> app (s-2 is unlinked)
        r = run(self.env, "--from", "deployments", "--days", "7")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual([l.split()[0] for l in r.stdout.splitlines() if " exit 0 " in l], ["deployments", "issues"])
        ro = self.readout()
        # runs 1,2 head commits of s-1 (1 fail of 2); 3,4,5 baseline (1 of 3); 6 cancelled counts in neither (D-rate)
        self.assertEqual(ro["deployments"], {"repos": 1, "runs": 6, "runs_linked": 2, "agent": {"failure_rate": 0.5, "n": 2},
                                             "baseline": {"failure_rate": 0.333333, "n": 3}})
        # PR 10 holds 1 of s-1's 2 linked commits -> $1.0 of $2.0; PR 11 has no ticket and no session
        self.assertEqual(ro["issues"], {"repos": 1, "prs": 2, "prs_merged": 1, "prs_linked": 1, "ticketless_share": 0.5,
                                        "cost_linked": 1.0, "issues": 1, "issues_closed_without_pr": 0, "truncated": []})
        self.assertEqual(self.calls()[0], "auth status")
        self.assertEqual(self.calls().count("auth status"), 1)
        self.assertTrue(os.path.exists(os.path.join(self.data, "deployments.jsonl")))

    def test_only_keeps_other_section(self):
        run(self.env, "--only", "issues")
        r = run(self.env, "--only", "deployments", "--no-network")
        self.assertEqual(r.returncode, 0, r.stderr)
        ro = self.readout()
        self.assertEqual(ro["deployments"], {"skipped": "network stages disabled"})
        self.assertEqual(ro["issues"]["prs"], 2)

    def assert_skipped(self, why, env=None, gh_calls=()):
        r = run(env or self.env, "--from", "deployments")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.splitlines(), [f"deployments skipped: {why}", f"issues   skipped: {why}"])
        self.assertEqual(self.readout(), {"v": 1, "generated": self.readout()["generated"],
                                          "deployments": {"skipped": why}, "issues": {"skipped": why}})
        self.assertEqual(self.calls(), list(gh_calls))
        self.assertFalse(os.path.exists(os.path.join(self.data, "deployments.jsonl")))

    def test_skip_no_network(self):
        r = run(self.env, "--from", "deployments", "--no-network")
        self.assertEqual(r.stdout.splitlines()[0], "deployments skipped: network stages disabled")
        self.assertEqual(self.calls(), [])

    def test_skip_unauthenticated(self):
        self.assert_skipped("gh not authenticated", dict(self.env, FAKE_GH_AUTH="0"), ["auth status"])

    def test_skip_gh_missing(self):
        b = os.path.join(self.tmp.name, "nogh")
        os.makedirs(b)
        os.symlink(shutil.which("git"), os.path.join(b, "git"))
        self.assert_skipped("gh not found", dict(self.env, PATH=b))

    def test_skip_no_repos(self):
        open(os.path.join(self.data, "impact.jsonl"), "w").close()
        self.assert_skipped("no repos")

    def test_repos_from_config_and_readout_edge(self):
        pipe = pipeline()
        cfg = {"impact": {"repos": [os.path.join(self.repo, "sub"), "me/other"]}}
        self.assertEqual(pipe.repos_for(cfg, self.data), [os.path.realpath(self.repo), "me/other"])
        with unittest.mock.patch.dict(os.environ, HOME=self.tmp.name):
            self.assertEqual(pipe.repos_for({"impact": {"repos": []}}, self.data), [os.path.realpath(self.repo)])
        with open(os.path.join(self.data, "issues_summary.json"), "w") as f:
            json.dump({"repos_scanned": 0, "truncated": [], "prs": 0, "prs_merged": 0, "prs_with_session": 0,
                       "prs_without_ticket": 0, "issues": 0, "issues_closed_without_pr": 0, "cost_linked": 0.0}, f)
        self.assertIsNone(pipe.readout_issues(self.data)["ticketless_share"])


class LocalStages(unittest.TestCase):
    """quality + mcp as pipeline stages on the 04-auto-analysis fixtures: one transcripts dir, ~/.claude.json in a temp HOME."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.data, tr = os.path.join(d, "data"), os.path.join(d, "transcripts")
        shutil.copytree(os.path.join(AUTO, "quality", "claude"), tr)
        shutil.copytree(os.path.join(AUTO, "mcp_usage", "projects"), tr, dirs_exist_ok=True)
        with open(os.path.join(AUTO, "mcp_usage", "claude.json")) as f, open(os.path.join(d, ".claude.json"), "w") as g:
            g.write(f.read().replace("PROJ", os.path.join(AUTO, "mcp_usage", "proj")))
        self.cfg = os.path.join(d, "config.json")
        with open(self.cfg, "w") as f:
            json.dump({"data_dir": self.data, "readers": {"paths": {"claude-code": tr}}}, f)
        self.env = {k: v for k, v in os.environ.items() if k not in ("OTM_DATA_DIR", "OTM_LEDGER")}
        self.env.update(OTM_CONFIG=self.cfg, HOME=d, PATH=fake_gh_bin(d) + os.pathsep + os.environ["PATH"])

    def tearDown(self):
        self.tmp.cleanup()

    def readout(self):
        with open(os.path.join(self.data, "readout.json")) as f:
            return json.load(f)

    def test_quality_and_mcp_readout(self):
        for stage in ("quality", "mcp"):
            r = run(self.env, "--only", stage, "--days", "3650")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn(f"{stage:8}", r.stdout)
        ro = self.readout()
        with open(os.path.join(self.data, "quality_summary.json")) as f:
            qs = json.load(f)
        self.assertEqual(ro["quality"], {k: qs[k] for k in ro["quality"]})  # same names and values as the reader
        self.assertEqual(set(ro["quality"]), {"sessions", "tool_error_rate", "test_runs", "test_fail_rate", "commits",
                                              "commits_without_test", "risky", "file_rework_rate", "commit_rework_rate"})
        self.assertEqual(set(ro["quality"]["risky"]), {"destructive", "exfiltration", "secrets"})
        self.assertGreater(ro["quality"]["sessions"], 0)
        self.assertEqual(ro["quality"]["commits"], 0)  # no impact.jsonl: no commit records
        m = ro["mcp"]
        self.assertTrue(m["servers_used"])
        self.assertLessEqual(len(m["servers_used"]), 5)
        self.assertEqual(set(m["servers_used"][0]), {"server", "calls", "errors", "context_share"})
        self.assertEqual(m["servers_called"], len(m["servers_used"]))
        self.assertIn("gh", m["never_called"] + [s["server"] for s in m["servers_used"]])
        self.assertAlmostEqual(m["mcp_ctx_share_of_tools"], sum(s["context_share"] for s in m["servers_used"]), places=5)
        self.assertLess(len(json.dumps(ro["mcp"])) + len(json.dumps(ro["quality"])), 2000)

    def test_failure_skips_and_continues(self):  # quality's script is missing: python exits 2, mcp still runs
        os.makedirs(self.data)
        with open(os.path.join(self.data, "quality_summary.json"), "w") as f:
            f.write("{")  # malformed output a failed run left behind
        pipe = pipeline()
        with unittest.mock.patch.object(pipe, "STAGES", [s if s[0] != "quality" else s[:1] + ("nope.py",) + s[2:] for s in pipe.STAGES]), \
                unittest.mock.patch.dict(os.environ, self.env, clear=True):
            code = pipe.main(["--from", "quality", "--no-network"])
        self.assertEqual(code, 0)
        ro = self.readout()
        self.assertTrue(ro["quality"]["skipped"].startswith("exit 2: "), ro["quality"])
        self.assertLessEqual(len(ro["quality"]["skipped"]), 200)
        self.assertIn("servers_used", ro["mcp"])
        self.assertEqual(ro["deployments"], {"skipped": "network stages disabled"})

    def test_bad_output_skips(self):  # stage exits 0 but its output is unreadable
        os.makedirs(self.data)
        with open(os.path.join(self.data, "mcp_usage.jsonl"), "w") as f:
            f.write("{not json\n")
        pipe = pipeline()
        ok = os.path.join(self.tmp.name, "ok.py")  # absolute: os.path.join(ROOT, ok) keeps it
        with open(ok, "w") as f:
            f.write("pass\n")
        with unittest.mock.patch.object(pipe, "STAGES", [("mcp", ok, False, "mcp_usage.jsonl", "local")]), \
                unittest.mock.patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(pipe.main([]), 0)
        self.assertTrue(self.readout()["mcp"]["skipped"].startswith("readout: JSONDecodeError"))


if __name__ == "__main__":
    unittest.main()
