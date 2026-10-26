"""impact: builds a throwaway git repo and checks the METHOD.md worked example (L-ex)."""
import importlib.util, json, os, subprocess, sys, tempfile, unittest

import pathlib  # numbered stage dirs aren't importable: find the repo, use 02-measure/ for imports
REPO = str(next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir()))
MEASURE = os.path.join(REPO, "02-measure")
sys.path.insert(0, MEASURE)
from schemas.check import check_file

FIX = os.path.join(REPO, "04-auto-analysis", "tests", "fixtures", "impact")
ENTRY = os.path.join(REPO, "04-auto-analysis", "impact", "impact.py")
_spec = importlib.util.spec_from_file_location("impact_main", ENTRY)
impact = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(impact)

ME, OTHER = "me@example.com", "other@example.com"


def git(repo, *args, date=None, email=ME):
    env = dict(os.environ, GIT_AUTHOR_NAME="u", GIT_AUTHOR_EMAIL=email, GIT_COMMITTER_NAME="u",
               GIT_COMMITTER_EMAIL=email, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    return subprocess.run(["git", "-C", repo, *args], env=env, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo, name, lines, date, msg="change", email=ME):
    with open(os.path.join(repo, name), "a") as f:
        f.write("x\n" * lines)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", msg, date=date, email=email)
    return git(repo, "rev-parse", "HEAD")


class Impact(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = repo = os.path.join(cls.tmp.name, "app")
        os.mkdir(repo)
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.email", ME)
        claude = "change\n\nCo-Authored-By: Claude <noreply@anthropic.com>"
        cls.c1 = commit(repo, "a.txt", 10, "2026-10-01T10:30:00Z", claude)
        cls.c2 = commit(repo, "b.txt", 5, "2026-10-01T11:20:00Z", claude)    # in POST_MIN
        cls.c3 = commit(repo, "c.txt", 4, "2026-10-01T13:00:00Z", claude)    # out of every window
        cls.c4 = commit(repo, "d.txt", 7, "2026-10-01T14:10:00Z")            # local, no trailer -> window
        cls.c5 = commit(repo, "e.txt", 3, "2026-10-01T14:20:00Z", email=OTHER)  # not local -> ignored
        git(repo, "revert", "--no-edit", cls.c2, date="2026-10-01T16:00:00Z")
        cls.c6 = git(repo, "rev-parse", "HEAD")
        with open(os.path.join(FIX, "sessions.jsonl")) as f:
            cls.sessions = [json.loads(l.replace("{repo}", repo)) for l in f if l.strip()]
        cls.cfg = {"impact": {"vcs": "local_git", "repos": [], "read_subjects": False}}
        cls.now = impact.ts("2026-10-02T00:00:00Z")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_impact(self, answers=None):
        recs, summary = impact.run(self.sessions, self.cfg, answers or {}, self.now)
        return {r["session_id"]: r for r in recs}, summary

    def test_first_pass(self):
        recs, s = self.run_impact()
        a, b = recs["s-a"], recs["s-b"]
        self.assertEqual(set(recs), {"s-a", "s-b"})
        self.assertEqual((a["link"], a["link_p"]), ("trailer", 1.0))
        self.assertEqual([c["sha"] for c in a["commits"]], [self.c1, self.c2])
        self.assertEqual((a["added"], a["commits_kept"], a["commits_reverted"]), (15, 1, 1))
        self.assertEqual(a["commits"][1]["reverted_by"], self.c6)
        self.assertEqual(a["commits"][0]["agent_trailer"], "claude-code")
        self.assertTrue(a["commits"][0]["on_default_branch"])
        self.assertEqual((b["link"], b["link_p"], [c["sha"] for c in b["commits"]]), ("window", None, [self.c4]))
        self.assertEqual((s["sessions_total"], s["sessions_linked"], s["repos_scanned"]), (3, 1, 1))
        self.assertEqual(s["by_repo"], [{"repo_label": "app", "cost": 2.0, "sessions": 1, "commits_kept": 1,
                                         "commits_reverted": 1, "lines_added": 10, "cost_per_kept_commit": 2.0,
                                         "cost_per_100_lines": 20.0, "revert_rate": 0.5}])
        self.assertEqual(s["unlinked_cost"], 1.5)

    def test_outside(self):  # L-outside: null-repo session gets a trailer commit only when impact.repos is set
        o = dict(self.sessions[0], session_id="s-o", repo=None, project="projects",
                 start="2026-10-01T12:40:00Z", end="2026-10-01T12:50:00Z")
        cfg = {"impact": dict(self.cfg["impact"], repos=[self.repo])}
        recs = {r["session_id"]: r for r in impact.run(self.sessions + [o], cfg, {}, self.now)[0]}
        self.assertEqual((recs["s-o"]["link_p"], [c["sha"] for c in recs["s-o"]["commits"]]), (impact.OUTSIDE_P, [self.c3]))
        self.assertEqual(recs["s-a"]["link_p"], 1.0)
        self.assertNotIn("s-o", {r["session_id"] for r in impact.run(self.sessions + [o], self.cfg, {}, self.now)[0]})

    def test_outside_nested(self):  # L-outside: session whose repo is a parent dir of R (nested repo, git -C)
        o = dict(self.sessions[0], session_id="s-n", repo=self.tmp.name, start="2026-10-01T12:40:00Z", end="2026-10-01T12:50:00Z")
        cfg = {"impact": dict(self.cfg["impact"], repos=[self.repo])}
        recs = {r["session_id"]: r for r in impact.run(self.sessions + [o], cfg, {}, self.now)[0]}
        self.assertEqual((recs["s-n"]["link_p"], [c["sha"] for c in recs["s-n"]["commits"]]), (impact.OUTSIDE_P, [self.c3]))

    def test_assign_prefers_big_writer(self):  # L-assign: tiny automated session and non-writer lose c1 to s-a / s-w
        tiny = dict(self.sessions[0], session_id="s-t", calls=1, tools={}, start="2026-10-01T10:29:00Z", end="2026-10-01T10:31:00Z")
        recs = {r["session_id"]: r for r in impact.run(self.sessions + [tiny], self.cfg, {}, self.now)[0]}
        self.assertNotIn("s-t", recs)
        self.assertEqual([c["sha"] for c in recs["s-a"]["commits"]], [self.c1, self.c2])
        writer = dict(self.sessions[0], session_id="s-w", calls=10, tools={"Bash": 2}, start="2026-10-01T09:00:00Z")
        recs = {r["session_id"]: r for r in impact.run(self.sessions + [writer], self.cfg, {}, self.now)[0]}
        self.assertEqual(([c["sha"] for c in recs["s-w"]["commits"]], "s-a" in recs), ([self.c1, self.c2], False))

    def test_split_cost(self):  # L-split: one outside session in two repos; by_repo and by_harness sum to its cost
        claude = "change\n\nCo-Authored-By: Claude <noreply@anthropic.com>"
        with tempfile.TemporaryDirectory() as t:
            other = os.path.join(t, "lib")
            os.mkdir(other)
            git(other, "init", "-q", "-b", "main")
            commit(other, "x.txt", 2, "2026-10-01T12:45:00Z", claude)
            commit(other, "y.txt", 2, "2026-10-01T12:46:00Z", claude)
            o = dict(self.sessions[0], session_id="s-o", repo=None, project="projects", cost=dict(self.sessions[0]["cost"], total=3.0),
                     start="2026-10-01T12:40:00Z", end="2026-10-01T12:50:00Z")
            cfg = {"impact": dict(self.cfg["impact"], repos=[self.repo, other])}
            _, s = impact.run(self.sessions + [o], cfg, {}, self.now)
        by = {r["repo_label"]: r["cost"] for r in s["by_repo"]}
        self.assertEqual(by, {"app": 3.0, "lib": 2.0})  # s-a 2.0 + 1/3 of s-o in app, 2/3 of s-o in lib
        self.assertAlmostEqual(sum(by.values()), 5.0)
        self.assertAlmostEqual(sum(r["cost"] for r in s["by_harness"]), 5.0)

    def test_decided(self):
        subj = impact.subject_of("s-b", [self.c4])
        recs, s = self.run_impact({subj: 0.8})
        self.assertEqual(recs["s-b"]["link_p"], 0.8)
        self.assertEqual((s["sessions_linked"], s["by_repo"][0]["cost"], s["by_repo"][0]["lines_added"]), (2, 3.0, 17))
        self.assertEqual(s["unlinked_cost"], 0.5)
        recs, s = self.run_impact({subj: 0.3})  # below MIN_P -> dropped
        self.assertNotIn("s-b", recs)
        self.assertEqual(s["unlinked_cost"], 1.5)

    def test_roundtrip_decide(self):  # L-subject = D-commit-link subject; pass1 -> decide (stub) -> pass2
        spec = importlib.util.spec_from_file_location("decide_for_impact", os.path.join(REPO, "06-optional", "decide", "decide.py"))
        D = importlib.util.module_from_spec(spec); spec.loader.exec_module(D)
        recs, _ = self.run_impact()
        with tempfile.TemporaryDirectory() as d:
            for name, rows in (("sessions.jsonl", self.sessions), ("impact.jsonl", recs.values())):
                with open(os.path.join(d, name), "w") as f:
                    f.writelines(json.dumps(r) + "\n" for r in rows)
            with open(os.path.join(REPO, "06-optional", "tests", "fixtures", "decide", "analysis.json")) as f, open(os.path.join(d, "analysis.json"), "w") as g:
                g.write(f.read())
            self.assertEqual(D.run(d, d, {"decide": {"vendor": "stub", "points": []}})["asked"], 1)
            answers = impact.decided(impact.read_jsonl(os.path.join(d, "decisions.jsonl")))
        subj = impact.subject_of("s-b", [self.c4])
        self.assertEqual(list(answers), [subj])
        recs2, _ = self.run_impact(answers)
        if answers[subj] >= impact.MIN_P:
            self.assertEqual(recs2["s-b"]["link_p"], answers[subj])
        else:
            self.assertNotIn("s-b", recs2)

    def test_decided_latest_wins(self):
        d = lambda t, p: {"point": "commit_link", "subject": "x", "ts": t, "probabilities": {"yes": p, "no": 1 - p}}
        self.assertEqual(impact.decided([d("2026-10-02T00:00:00Z", 0.9), d("2026-10-01T00:00:00Z", 0.1)]), {"x": 0.9})

    def test_cli_outputs_valid(self):
        with tempfile.TemporaryDirectory() as d:
            sessions = os.path.join(d, "sessions.jsonl")
            with open(sessions, "w") as f:
                f.writelines(json.dumps(s) + "\n" for s in self.sessions)
            cfg = os.path.join(d, "config.json")
            with open(cfg, "w") as f:
                f.write("{}")
            env = dict(os.environ, OTM_DATA_DIR=d)
            r = subprocess.run([sys.executable, ENTRY, "--days", "100000", "--config", cfg, "--sessions", sessions, "--out", d],
                               env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(check_file(os.path.join(d, "impact.jsonl"), "impact"), [])
            self.assertEqual(check_file(os.path.join(d, "impact_summary.json"), "impact_summary"), [])


if __name__ == "__main__":
    unittest.main()
