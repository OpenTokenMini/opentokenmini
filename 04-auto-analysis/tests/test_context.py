"""context: synthetic transcripts in a temp dir (no network); checks the METHOD.md worked example (X-ex)."""
import importlib.util, json, os, sys, tempfile, unittest

import pathlib  # numbered stage dirs aren't importable: find the repo
REPO = str(next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir()))
ENTRY = os.path.join(REPO, "04-auto-analysis", "context", "context.py")
_spec = importlib.util.spec_from_file_location("context_main", ENTRY)
cx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cx)
MODEL = "claude-sonnet-4"


def ai(rid, minute, inp, cr, cw, tool=None, side=False):
    m = {"model": MODEL, "usage": {"input_tokens": inp, "cache_read_input_tokens": cr, "cache_creation_input_tokens": cw,
                                   "output_tokens": 1}, "content": [{"type": "tool_use", **tool}] if tool else []}
    return {"type": "assistant", "requestId": rid, "sessionId": "s1", "isSidechain": side, "cwd": "/home/u/app",
            "timestamp": f"2026-10-02T10:{minute:02d}:00Z", "message": m}


def res(uid, text, minute):
    return {"type": "user", "sessionId": "s1", "timestamp": f"2026-10-02T10:{minute:02d}:30Z",
            "message": {"content": [{"type": "tool_result", "tool_use_id": uid, "content": text}]}}


MAIN = [
    dict(ai("r0", 0, 0, 999999, 0), timestamp="2026-09-30T10:00:00Z"),  # before since: dropped
    ai("r1", 1, 10, 0, 1000, {"id": "u1", "name": "Read", "input": {"file_path": "/a"}}),
    ai("r1", 1, 10, 0, 1000, {"id": "u1", "name": "Read", "input": {"file_path": "/a"}}),  # same request logged twice
    res("u1", "x" * 400, 1),
    ai("r2", 2, 5, 1000, 200, {"id": "u2", "name": "Read", "input": {"file_path": "/a"}}),
    res("u2", "y" * 400, 2),
    ai("r3", 3, 1, 1200, 0, {"id": "u3", "name": "Edit", "input": {"file_path": "/a"}}),
    res("u3", "ok", 3),
    ai("r4", 4, 1, 1200, 50, {"id": "u4", "name": "Read", "input": {"file_path": "/a"}}),
    res("u4", "z" * 8, 4),
    {"type": "system", "subtype": "compact_boundary", "sessionId": "s1", "timestamp": "2026-10-02T10:05:00Z",
     "compactMetadata": {"trigger": "auto", "preTokens": 1300, "postTokens": 300}},
    ai("r5", 6, 0, 300, 0, {"id": "u5", "name": "Bash", "input": {"command": "ls"}}),
    res("u5", "b" * 4000, 6),
]
SUB = [ai("r6", 7, 1, 0, 160000, {"id": "u6", "name": "Read", "input": {"file_path": "/a"}}, side=True), res("u6", "qqqq", 7)]
S2 = [dict(ai("r7", 8, 0, 260000, 0), sessionId="s2")]


class Context(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = os.path.join(cls.tmp.name, "-home-u-app")
        os.makedirs(os.path.join(d, "s1", "subagents"))
        for path, lines in (("s1.jsonl", MAIN), ("s1/subagents/agent-1.jsonl", SUB), ("s2.jsonl", S2)):
            with open(os.path.join(d, path), "w") as f:
                f.writelines(json.dumps(l) + "\n" for l in lines)
        cls.r = cx.run(cls.tmp.name, cx.datetime(2026, 10, 1, tzinfo=cx.timezone.utc))
        cls.a = cls.r["aggregate"]
        cls.s = {s["session_id"]: s for s in cls.r["sessions"]}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_ctx_and_peak(self):  # X-ctx, X-peak: main thread only, dedup by request id, old line dropped
        s1 = self.s["s1"]
        self.assertEqual(s1["curve"], [1010, 1205, 1201, 1251, 300])
        self.assertEqual((s1["turns"], s1["peak_ctx"]), (5, 1251))  # subagent's 160001 not in the main curve
        self.assertEqual((self.a["over_150k"], self.a["over_250k"], self.a["peak_ctx_max"]), (1, 1, 260000))
        self.assertEqual(self.r["curve_median"], {"1": (1010 + 260000) // 2})

    def test_compactions(self):  # X-compact
        self.assertEqual(self.s["s1"]["compactions"], [[1300, 300]])
        self.assertEqual((self.a["compactions"], self.a["compact_pre_p50"], self.a["compact_post_p50"]), (1, 1300, 300))

    def test_cache_mix_and_cost(self):  # X-cache: subagent calls count in the mix and cost
        inp, cr, cw = 18, 3700 + 260000, 161250
        self.assertEqual(self.a["input_share"]["cache_read"], round(cr / (inp + cr + cw), 4))
        self.assertAlmostEqual(self.s["s1"]["cache_write_cost"], round(cw * 3.75 / 1e6, 4))

    def test_reread(self):  # X-reread: 2nd identical read counts; an Edit resets; subagent is its own thread
        self.assertEqual((self.a["reread_count"], self.a["reread_tokens"]), (1, 100))

    def test_tools(self):  # X-tools, X-size
        self.assertEqual([(t["tool"], t["result_tokens"], t["calls"]) for t in self.a["tools_by_result_tokens"]],
                         [("Bash", 1000, 1), ("Read", 203, 4), ("Edit", 1, 1)])

    def test_readout_small_no_paths(self):  # X-readout
        ro = json.dumps(self.r["readout"], separators=(",", ":"))
        self.assertLess(len(ro), cx.MAX_READOUT_BYTES)
        self.assertEqual(self.r["readout"]["detail"], cx.OUT)
        self.assertTrue(self.r["readout"]["findings"])
        self.assertNotIn("/a", json.dumps(self.r))

    def test_pipeline_readout(self):  # pipeline stage "context" copies the readout into readout.json
        spec = importlib.util.spec_from_file_location("pipeline_ctx", os.path.join(REPO, "03-analyze", "pipeline.py"))
        pl = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pl)
        with tempfile.TemporaryDirectory() as data:
            with open(os.path.join(data, cx.OUT), "w") as f:
                json.dump(self.r, f)
            self.assertEqual(pl.READOUTS["context"](data, []), self.r["readout"])
        self.assertIn("context", pl.NAMES)


if __name__ == "__main__":
    unittest.main()
