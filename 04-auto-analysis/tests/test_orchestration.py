"""orchestration: synthetic transcripts in a temp dir (no network). s1 = deep (a sync, b async + failed, b launches c), s2 = single helper, s3 = no delegation."""
import importlib.util, json, os, tempfile, unittest
from datetime import datetime, timezone

import pathlib  # numbered stage dirs aren't importable: find the repo
REPO = str(next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir()))
ENTRY = os.path.join(REPO, "04-auto-analysis", "orchestration", "orchestration.py")
_spec = importlib.util.spec_from_file_location("orchestration_main", ENTRY)
oc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oc)
MODEL = "claude-sonnet-4"
SINCE = datetime(2000, 1, 1, tzinfo=timezone.utc)


def t(minute):
    return f"2026-10-02T10:{minute:02d}:00Z"


def ai(mid, minute, *tools):
    return {"type": "assistant", "timestamp": t(minute),
            "message": {"id": mid, "model": MODEL, "content": [{"type": "tool_use", **x} for x in tools],
                        "usage": {"input_tokens": 10, "cache_read_input_tokens": 1000, "output_tokens": 5}}}


def agent(tid):
    return {"id": tid, "name": "Agent", "input": {"prompt": "do it"}}


def result(tid, text, minute, status="completed"):
    return {"type": "user", "timestamp": t(minute), "toolUseResult": {"status": status},
            "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": text}]}}


def note(tid, status, size, minute):
    body = f"<task-notification><tool-use-id>{tid}</tool-use-id><status>{status}</status><result>{'x' * size}</result></task-notification>"
    return {"type": "user", "timestamp": t(minute), "message": {"content": body}}


def write(path, lines, meta=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.writelines(json.dumps(l) + "\n" for l in lines)
    if meta is not None:
        with open(path[:-6] + ".meta.json", "w") as f:
            json.dump(meta, f)


class Orchestration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        p = os.path.join(cls.tmp.name, "proj")
        write(f"{p}/s1.jsonl", [
            ai("m1", 0, agent("ta"), agent("tb")),          # one turn launches a and b
            result("tb", "Async agent launched", 0, "async_launched"),
            result("ta", "r" * 400, 5),                      # a: sync, 400 chars = 100 tok
            note("tb", "failed", 40000, 10),                 # b: async, failed, ~10k tok -> huge
            ai("m2", 11, {"id": "g1", "name": "Bash", "input": {"command": "git -C /r commit -m x"}}),
        ])
        sub = f"{p}/s1/subagents"
        write(f"{sub}/agent-a.jsonl", [ai("a1", 1), ai("a2", 4)], {"toolUseId": "ta", "spawnDepth": 1})
        write(f"{sub}/agent-b.jsonl", [ai("b1", 1, agent("tc")), ai("b2", 9)], {"toolUseId": "tb", "spawnDepth": 1})
        write(f"{sub}/agent-c.jsonl", [ai("c1", 2), ai("c2", 3)], {"toolUseId": "tc", "spawnDepth": 2, "parentAgentId": "b"})
        write(f"{p}/s2.jsonl", [ai("n1", 0, agent("th")), result("th", "done", 3)])
        write(f"{p}/s2/subagents/agent-h.jsonl", [ai("h1", 1), ai("h2", 2)], {"toolUseId": "th"})
        write(f"{p}/s3.jsonl", [ai("q1", 0, {"id": "x", "name": "Read", "input": {"file_path": "/a"}})])
        cls.recs = {r["session_id"]: r for r in oc.scan(cls.tmp.name, SINCE)}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_sessions(self):
        self.assertEqual(set(self.recs), {"s1", "s2"})  # s3 delegated nothing

    def test_deep(self):
        s = self.recs["s1"]
        got = {k: s[k] for k in ("topology", "workers", "workers_linked", "batches", "max_batch", "max_concurrent",
                                 "max_depth", "huge_results", "worker_errors", "batches_committed")}
        self.assertEqual(got, {"topology": "deep", "workers": 3, "workers_linked": 3, "batches": 1, "max_batch": 2,
                               "max_concurrent": 2, "max_depth": 2, "huge_results": 1, "worker_errors": 1,
                               "batches_committed": 1})
        w = {x["agent"]: x for x in s["worker_list"]}
        self.assertEqual((w["a"]["launcher"], w["b"]["launcher"], w["c"]["launcher"]), ("orchestrator", "orchestrator", "b"))
        self.assertEqual(w["a"]["result_tokens"], 100)
        self.assertGreater(w["b"]["result_tokens"], 10000)
        self.assertTrue(w["b"]["error"] and not w["a"]["error"])
        self.assertEqual(s["result_tokens_max"], w["b"]["result_tokens"])
        self.assertGreater(s["worker_cost"], 0)
        self.assertGreater(s["orchestrator_cost"], 0)

    def test_single_helper(self):
        s = self.recs["s2"]
        self.assertEqual((s["topology"], s["workers"], s["batches"], s["max_concurrent"], s["huge_results"], s["worker_errors"]),
                         ("single-helper", 1, 1, 1, 0, 0))

    def test_summary(self):
        s = oc.summarize(list(self.recs.values()))
        self.assertEqual((s["sessions"], s["workers"], s["topologies"]), (2, 4, {"deep": 1, "single-helper": 1}))
        self.assertEqual((s["batches"], s["batches_committed"], s["workers_unlinked"]), (2, 1, 0))
        self.assertLess(len(json.dumps(s["readout"])), oc.READOUT_BYTES)
        self.assertIn("findings", s["readout"])
        self.assertEqual(oc.summarize([])["readout"]["sessions"], 0)

    def test_no_content_in_output(self):
        dump = json.dumps(list(self.recs.values()))
        for leak in ("do it", "git -C", "rrrr", "xxxx"):
            self.assertNotIn(leak, dump)


if __name__ == "__main__":
    unittest.main()
