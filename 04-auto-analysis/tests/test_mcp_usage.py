"""mcp_usage: fixture transcripts and configs (no network); checks the METHOD.md worked example (M-ex)."""
import importlib.util, json, os, subprocess, sys, tempfile, unittest

import pathlib  # numbered stage dirs aren't importable: find the repo, use 02-measure/ for imports
REPO = str(next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir()))
sys.path.insert(0, os.path.join(REPO, "02-measure"))
from schemas.check import check_file

FIX = os.path.join(REPO, "04-auto-analysis", "tests", "fixtures", "mcp_usage")
SCHEMA = os.path.join(FIX, "mcp_usage.schema.json")
ENTRY = os.path.join(REPO, "04-auto-analysis", "mcp-usage", "mcp_usage.py")
_spec = importlib.util.spec_from_file_location("mcp_usage_main", ENTRY)
mu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mu)


class McpUsage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        with open(os.path.join(FIX, "claude.json")) as f:  # point the project entry at the fixture dir holding .mcp.json
            cj = json.load(f)
        cj["projects"] = {os.path.join(FIX, "proj"): cj["projects"]["PROJ"]}
        self.cj = os.path.join(self.tmp.name, "claude.json")
        with open(self.cj, "w") as f:
            json.dump(cj, f)
        self.since = mu.datetime(2026, 10, 1, tzinfo=mu.timezone.utc)
        self.recs = mu.run(os.path.join(FIX, "projects"), self.cj, self.since)
        self.srv = {r["server"]: r for r in self.recs if r["kind"] == "server"}
        self.tool = {(r["server"], r["tool"]): r for r in self.recs if r["kind"] == "tool"}

    def tearDown(self):
        self.tmp.cleanup()

    def test_servers(self):  # M-config, M-loaded: called, configured, loaded and disabled servers all listed
        self.assertEqual(sorted(self.srv), ["claude_ai_Docs", "claude_ai_Gmail", "docs_server", "gh", "unused-db"])
        self.assertEqual({s: r["config"] for s, r in self.srv.items()},
                         {"claude_ai_Docs": "none", "claude_ai_Gmail": "disabled", "docs_server": "enabled",
                          "gh": "enabled", "unused-db": "enabled"})
        self.assertEqual({s: r["loaded_sessions"] for s, r in self.srv.items()},
                         {"claude_ai_Docs": 0, "claude_ai_Gmail": 0, "docs_server": 1, "gh": 1, "unused-db": 0})
        self.assertEqual(sorted(s for s, r in self.srv.items() if r["never_called"]),
                         ["claude_ai_Gmail", "docs_server", "unused-db"])

    def test_counts_and_size(self):  # M-scan, M-size: t0 before since dropped; is_error counted; image = IMAGE_TOKENS
        gh = self.srv["gh"]
        self.assertEqual((gh["calls"], gh["errors"], gh["input_tokens_est"], gh["result_tokens_est"], gh["sessions"]),
                         (2, 1, 6, 110, 1))
        self.assertEqual((gh["first"], gh["last"]), ("2026-10-02T10:01:00Z", "2026-10-02T10:02:00Z"))
        self.assertEqual(self.tool[("gh", "get_issue")]["errors"], 1)
        self.assertEqual(self.tool[("gh", "search")]["result_tokens_est"], 100)
        self.assertEqual(self.srv["claude_ai_Docs"]["result_tokens_est"], mu.IMAGE_TOKENS)
        self.assertEqual(self.srv["claude_ai_Docs"]["sessions"], 1)  # subagent transcript, parent sessionId
        self.assertNotIn(("Bash", None), self.tool)

    def test_context_share(self):  # M-agg: share over all tool calls; total = 104 + 12 + 25 (Bash) + 1501
        self.assertEqual(self.srv["gh"]["context_share"], round(116 / 1642, 6))
        self.assertEqual(self.srv["claude_ai_Docs"]["context_share"], round(1501 / 1642, 6))
        self.assertEqual(self.srv["docs_server"]["context_share"], 0.0)

    def test_no_secrets(self):  # M-config: only names leave the config files
        dump = json.dumps(self.recs)
        for s in ("secret", "gh-mcp", "example.invalid", "GH_TOKEN"):
            self.assertNotIn(s, dump)

    def test_names(self):  # M-name
        self.assertEqual(mu.split("mcp__claude_ai_Docs__read"), ("claude_ai_Docs", "read"))
        self.assertEqual(mu.norm("claude.ai Google Drive"), "claude_ai_Google_Drive")

    def test_records_valid(self):
        path = os.path.join(self.tmp.name, "mcp_usage.jsonl")
        with open(path, "w") as f:
            f.writelines(json.dumps(r) + "\n" for r in self.recs)
        self.assertEqual(check_file(path, SCHEMA), [])

    def test_cli(self):  # entry point end to end on fixtures, no network
        out, cfg = os.path.join(self.tmp.name, "out"), os.path.join(self.tmp.name, "config.json")
        with open(cfg, "w") as f:
            f.write("{}")
        p = subprocess.run([sys.executable, ENTRY, "--days", "100000", "--root", os.path.join(FIX, "projects"),
                            "--claude-json", self.cj, "--out", out], capture_output=True, text=True, cwd=REPO,
                           env={**os.environ, "OTM_CONFIG": cfg})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("5 servers", p.stdout)
        self.assertTrue(os.path.exists(os.path.join(out, "mcp_usage.jsonl")))


if __name__ == "__main__":
    unittest.main()
