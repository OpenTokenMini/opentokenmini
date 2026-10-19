"""Readers on synthetic fixtures. Worked examples from readers/METHOD.md."""
import json, os, sqlite3, sys, tempfile, unittest
from datetime import datetime, timezone

import pathlib  # numbered stage dirs aren't importable: find the repo, use 02-measure/ for imports
REPO = str(next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir()))
MEASURE = os.path.join(REPO, "02-measure")
sys.path[:0] = [MEASURE, os.path.join(MEASURE, "readers")]
import common, readers, antigravity, claude_code
from schemas.check import validate

FIX = os.path.join(MEASURE, "tests", "fixtures", "readers")
SINCE = datetime(2026, 9, 1, tzinfo=timezone.utc)
common.HOME = "/home/user"


def vint(n):
    out = b""
    while True:
        b, n = n & 0x7F, n >> 7
        out += bytes([b | (0x80 if n else 0)])
        if not n:
            return out


def field(f, v):
    return vint(f << 3) + vint(v) if isinstance(v, int) else vint(f << 3 | 2) + vint(len(v)) + v


def make_dbs(d):
    oc = os.path.join(d, "opencode.db")
    db = sqlite3.connect(oc)
    db.executescript("create table session(id, directory, parent_id); create table message(id, session_id, time_created, data);"
                     "create table part(message_id, time_created, data);")
    db.execute("insert into session values ('oc-1', '/home/user/projects/demo/app', null)")
    t = 1790848800000  # 2026-10-01T10:00:00Z
    msgs = [("u1", {"role": "user", "content": "LEAKCANARY"}),
            ("a1", {"role": "assistant", "modelID": "moonshotai/kimi-k3", "providerID": "openrouter", "cost": 0.0247032,
                    "tokens": {"input": 7898, "output": 13, "reasoning": 53, "cache": {"read": 64, "write": 0}},
                    "time": {"created": t + 1000, "completed": t + 5000}}),
            ("a2", {"role": "assistant", "modelID": "x", "cost": 0, "tokens": {"input": 0, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}}})]
    for i, (mid, data) in enumerate(msgs):
        db.execute("insert into message values (?, 'oc-1', ?, ?)", (mid, t + 1000 * i, json.dumps(data)))
    db.execute("insert into part values ('a1', ?, ?)", (t, json.dumps({"type": "tool", "tool": "bash", "state": {"input": "LEAKCANARY"}})))
    db.commit(); db.close()
    ag = os.path.join(d, "agy"); os.makedirs(ag)
    db = sqlite3.connect(os.path.join(ag, "conv-1.db"))
    db.executescript("create table gen_metadata(data); create table steps(idx, step_type, metadata);")
    db.execute("insert into gen_metadata values (?)", (field(1, field(19, b"gemini-3-flash")) + field(2, 1),))
    when = field(1, field(1, 1790848800))
    usage = field(9, field(2, 1000) + field(3, 100) + field(4, 0) + field(5, 4000))
    db.executemany("insert into steps values (?, ?, ?)", [(0, 14, when), (1, 15, when + usage), (2, 5, when + field(4, field(2, b"run_command")))])
    db.commit(); db.close()
    return oc, ag


class Readers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        oc, ag = make_dbs(cls.tmp.name)
        cls.cfg = {"readers": {"paths": {"claude-code": FIX + "/claude", "codex": FIX + "/codex", "pi": FIX + "/pi",
                                         "opencode": oc, "antigravity": ag}}}
        cls.events, cls.summary = readers.run(list(readers.READERS), SINCE, cls.cfg)
        cls.calls = {}
        for e in cls.events:
            if e["kind"] == "api_call":
                cls.calls.setdefault(e["harness"], []).append(e)

    def test_valid(self):
        for e in self.events:
            self.assertEqual(validate(e, "event"), [], e)
        self.assertTrue(all(s["error"] is None for s in self.summary.values()), self.summary)

    def test_no_leak(self):  # R-privacy
        out = os.path.join(self.tmp.name, "data", "events", "transcript.jsonl")
        readers.write(self.events, set(readers.READERS), out)
        with open(out) as f:
            text = f.read()
        self.assertNotIn("LEAKCANARY", text)
        self.assertNotIn("/home/user/models", text)

    def test_repo(self):  # R-repo: empty .git dir is not a repo; $HOME -> ~
        with tempfile.TemporaryDirectory() as t:
            os.makedirs(os.path.join(t, ".git", "info"))  # broken: no HEAD
            os.makedirs(os.path.join(t, "r", ".git"))
            open(os.path.join(t, "r", ".git", "HEAD"), "w").close()
            os.makedirs(os.path.join(t, "r", "sub"))
            home, common.HOME = common.HOME, t
            try:
                common._repos.clear()
                self.assertEqual(common.repo(os.path.join(t, "r", "sub")), "~/r")
                self.assertIsNone(common.repo(t))
            finally:
                common.HOME = home
                common._repos.clear()

    def test_claude(self):  # R-claude-dedup, R-claude-prompt, R-claude-ttl, R-claude-truncated, C-cost unknown
        c = {e["request_id"]: e for e in self.calls["claude-code"]}
        self.assertEqual(sorted(c), ["req_1", "req_2", "req_3"])
        self.assertEqual(c["req_1"]["tools"], ["Bash"])
        self.assertAlmostEqual(c["req_1"]["cost"]["total"], 0.018375)  # 5m 1500*3.75 + 1h 500*6 per Mtok
        self.assertEqual((c["req_1"]["tokens"]["cache_write_5m"], c["req_1"]["tokens"]["cache_write_1h"]), (1500, 500))
        self.assertEqual([c[r]["error"] for r in ("req_1", "req_2", "req_3")], [None, "truncated", None])
        self.assertEqual((c["req_2"]["cost_basis"], c["req_2"]["cost"]["total"]), ("unknown", 0.0))
        self.assertTrue(c["req_3"]["subagent"])
        self.assertEqual(c["req_1"]["project"], "demo/app")
        prompts = [e for e in self.events if e["harness"] == "claude-code" and e["kind"] == "user_prompt"]
        self.assertEqual(len(prompts), 1)

    def test_codex(self):  # R-codex-delta, R-codex-repeat
        a, b = self.calls["codex"]
        self.assertEqual(a["tokens"], {"input": 400, "output": 80, "cache_read": 600, "cache_write": 0, "reasoning": 20})
        self.assertEqual(b["tokens"], {"input": 500, "output": 170, "cache_read": 1000, "cache_write": 0, "reasoning": 30})
        self.assertAlmostEqual(a["cost"]["total"], 0.001575)
        self.assertAlmostEqual(b["cost"]["total"], 0.00275)
        self.assertEqual((a["parent_session_id"], a["subagent"], a["tools"]), ("cx-0", True, ["exec_command"]))

    def test_pi(self):  # R-pi-cost
        a, b = self.calls["pi"]
        self.assertEqual((a["tokens"]["output"], a["tokens"]["reasoning"], a["cost_basis"]), (75, 28, "reported"))
        self.assertAlmostEqual(a["cost"]["total"], 0.01644125)
        self.assertEqual((b["model"], b["cost_basis"]), ("Qwen3.5-0.8B-BF16.gguf", "unknown"))

    def test_opencode(self):  # R-opencode-empty, R-opencode-cost
        (a,) = self.calls["opencode"]
        self.assertEqual(a["tokens"], {"input": 7898, "output": 13, "cache_read": 64, "cache_write": 0, "reasoning": 53})
        self.assertEqual((a["cost_basis"], a["cost"]["total"], a["duration_ms"], a["tools"]),
                         ("reported_total_allocated", 0.0247032, 4000, ["bash"]))

    def test_antigravity(self):  # R-agy
        (a,) = self.calls["antigravity"]
        self.assertEqual((a["model"], a["tools"], a["tokens"]["cache_read"]), ("gemini-3-flash", ["run_command"], 4000))
        self.assertAlmostEqual(a["cost"]["total"], 0.001)  # (1000*0.5 + 100*3 + 4000*0.05) per Mtok
        self.assertEqual(antigravity.coverage, {})


class ClaudeAgentType(unittest.TestCase):  # R-claude-agent-type: agentType from agent-<id>.meta.json next to the subagent transcript
    def test_meta(self):
        line = {"sessionId": "s-sub-1", "cwd": "/home/user/projects/demo/app", "isSidechain": True, "type": "assistant",
                "timestamp": "2026-10-01T10:00:05.000Z", "requestId": "req_sub_1",
                "message": {"id": "msg_sub_1", "model": "claude-sonnet-4-6", "stop_reason": "end_turn",
                            "usage": {"input_tokens": 10, "output_tokens": 2}, "content": []}}
        with tempfile.TemporaryDirectory() as d:
            sub = os.path.join(d, "-home-user-projects-demo-app", "s-sub-1", "subagents")
            os.makedirs(sub)
            for name, meta in (("agent-a1", {"agentType": "Explore"}), ("agent-a2", None)):
                with open(os.path.join(sub, name + ".jsonl"), "w") as f:
                    f.write(json.dumps({**line, "requestId": "req_" + name}) + "\n")
                if meta:
                    with open(os.path.join(sub, name + ".meta.json"), "w") as f:
                        json.dump(meta, f)
            got = {e["request_id"]: e for e in claude_code.read(SINCE, {"readers": {"paths": {"claude-code": d}}})}
        self.assertEqual(got["req_agent-a1"]["agent_type"], "Explore")
        self.assertNotIn("agent_type", got["req_agent-a2"])
        for e in got.values():
            self.assertEqual(validate(e, "event"), [])


if __name__ == "__main__":
    unittest.main()
