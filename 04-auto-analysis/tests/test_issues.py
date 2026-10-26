"""issues: fake gh (fixtures/issues/graphql.json) + impact.jsonl; checks the METHOD.md worked example (I-ex). No network."""
import importlib.util, json, os, subprocess, sys, tempfile, unittest

import pathlib  # numbered stage dirs aren't importable: find the repo, use 02-measure/ for imports
REPO = str(next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir()))
sys.path.insert(0, os.path.join(REPO, "02-measure"))
from schemas.check import check_file, validate

FIX = os.path.join(REPO, "04-auto-analysis", "tests", "fixtures", "issues")
SCHEMA = "issue"  # 02-measure/schemas/issue.schema.json
ENTRY = os.path.join(REPO, "04-auto-analysis", "issues", "issues.py")
_spec = importlib.util.spec_from_file_location("issues_main", ENTRY)
issues = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(issues)

SESSIONS = [{"session_id": "s-a", "cost": {"total": 2.0}}, {"session_id": "s-b", "cost": {"total": 1.0}},
            {"session_id": "s-c", "cost": {"total": 0.5}}]


class FakeGh:
    """Serves fixture pages by GraphQL connection and cursor; records calls; fails on anything else."""
    def __init__(self, fail=()):
        with open(os.path.join(FIX, "graphql.json")) as f:
            self.pages = json.load(f)
        self.calls, self.fail = [], fail

    def __call__(self, args):
        q = next(a for a in args if a.startswith("query="))
        kind = "pullRequests" if "pullRequests(" in q else "issues"
        owner = next(a for a in args if a.startswith("owner="))[6:]
        after = next((a[6:] for a in args if a.startswith("after=")), None)
        self.calls.append((owner, kind, after))
        if owner in self.fail:
            raise RuntimeError("gh api graphql: Could not resolve to a Repository")
        return json.dumps(self.pages[kind][{None: 0, "p1": 1}[after]])  # KeyError if it pages past the cutoff


def make_repo(root, name, url):
    path = os.path.join(root, name)
    os.mkdir(path)
    subprocess.run(["git", "init", "-q", path], check=True)
    if url:
        subprocess.run(["git", "-C", path, "remote", "add", "origin", url], check=True)
    return path


class Issues(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = make_repo(cls.tmp.name, "app", "git@github.com:me/app.git")
        with open(os.path.join(FIX, "impact.jsonl")) as f:
            cls.impact = [json.loads(l) for l in f if l.strip()]
        cls.now = issues.datetime(2026, 10, 2, tzinfo=issues.timezone.utc)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_issues(self, repos=None, gh=None):
        recs, s = issues.run(repos or [self.repo], self.impact, SESSIONS, self.now, 30, gh or FakeGh())
        return {(r["kind"], r["number"]): r for r in recs}, s

    def test_fixture_impact_valid(self):
        self.assertEqual(check_file(os.path.join(FIX, "impact.jsonl"), "impact"), [])

    def test_prs(self):
        r, _ = self.run_issues()
        p10, p11, p12, p13 = (r[("pr", n)] for n in (10, 11, 12, 13))
        self.assertNotIn(("pr", 9), r)  # updated before the cutoff
        self.assertEqual((p10["state"], p10["type"], p10["issues"], p10["session_ids"], p10["cost"]), ("merged", "bug", [3], ["s-a"], 1.0))
        self.assertEqual(p10["merge_sha"], "d1" * 20)
        self.assertEqual((p11["type"], p11["keys"], p11["issues"], p11["session_ids"], p11["cost"]),
                         ("feature", ["PROJ-42"], [4, 5], ["s-a"], 1.0))  # b1 is pending in impact: not joined
        self.assertEqual((p12["state"], p12["issues"], p12["keys"], p12["cost"]), ("closed", [], [], 0.0))  # 12 is no issue
        self.assertEqual((p13["session_ids"], p13["cost"], p13["author"]), (["s-c"], 0.5, None))  # joined by merge sha
        self.assertEqual(p10["author"], issues.h12("dev1"))
        self.assertNotIn("title", p10)

    def test_issues(self):
        r, _ = self.run_issues()
        self.assertEqual((r[("issue", 3)]["prs"], r[("issue", 3)]["cost"], r[("issue", 3)]["session_ids"]), ([10], 1.0, ["s-a"]))
        self.assertEqual((r[("issue", 4)]["type"], r[("issue", 4)]["cost"], r[("issue", 5)]["cost"]), ("feature", 0.5, 0.5))
        self.assertEqual((r[("issue", 6)]["state_reason"], r[("issue", 6)]["prs"]), ("not_planned", []))
        self.assertEqual((r[("issue", 7)]["state"], r[("issue", 7)]["state_reason"]), ("open", None))

    def test_summary(self):
        _, s = self.run_issues()
        self.assertEqual({k: s[k] for k in ("repos_scanned", "truncated", "prs", "prs_merged", "prs_with_session",
                                            "prs_without_ticket", "issues", "issues_closed_without_pr", "cost_linked")},
                         {"repos_scanned": 1, "truncated": [], "prs": 4, "prs_merged": 3, "prs_with_session": 3,
                          "prs_without_ticket": 2, "issues": 5, "issues_closed_without_pr": 1, "cost_linked": 2.5})
        self.assertEqual(s["by_type"], [{"type": "bug", "prs": 1, "issues": 1, "sessions": 1, "cost": 1.0},
                                        {"type": "feature", "prs": 1, "issues": 1, "sessions": 1, "cost": 1.0},
                                        {"type": "none", "prs": 2, "issues": 3, "sessions": 1, "cost": 0.5}])

    def test_paging(self):  # I-fetch: stops at the first node older than the cutoff; truncated at MAX_PAGES
        gh = FakeGh()
        self.run_issues(gh=gh)
        self.assertEqual(gh.calls, [("me", "pullRequests", None), ("me", "pullRequests", "p1"), ("me", "issues", None)])
        old = issues.MAX_PAGES
        try:
            issues.MAX_PAGES = 1
            _, s = self.run_issues()
        finally:
            issues.MAX_PAGES = old
        self.assertEqual((s["truncated"], s["prs"]), (["app:pullRequests"], 2))

    def test_schema(self):
        r, s = self.run_issues()
        for rec in r.values():
            self.assertEqual(validate(rec, SCHEMA), [], rec)
        self.assertEqual(s["v"], 1)

    def test_repo_skips(self):  # I-repo: no GitHub remote or gh error -> skipped, others still read
        bare = make_repo(self.tmp.name, "local-only", None)
        gone = make_repo(self.tmp.name, "gone", "https://github.com/ghost/gone")
        _, s = self.run_issues([bare, gone, self.repo], FakeGh(fail=("ghost",)))
        self.assertEqual((s["repos_scanned"], s["prs"]), (1, 4))

    def test_slug_and_keys(self):
        self.assertEqual(issues.slug_of(self.repo), "me/app")
        m = issues.REMOTE_RX.search("https://github.com/Org/my.repo.git")
        self.assertEqual(m.groups(), ("Org", "my.repo"))
        self.assertEqual(issues.keys_of("ABC-1 fix (#7) and #8", "gh-9_x"), (["ABC-1"], {7, 8, 9}))
        self.assertEqual(issues.keys_of("v2-3 release", "main"), ([], set()))


if __name__ == "__main__":
    unittest.main()
