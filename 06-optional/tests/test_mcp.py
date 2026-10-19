import json, os, shutil, subprocess, sys, tempfile, unittest

import pathlib  # numbered stage dirs aren't importable: find the repo, use 02-measure/ for imports
REPO = str(next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir()))
MEASURE = os.path.join(REPO, "02-measure")
FIX = os.path.join(MEASURE, "tests", "fixtures")  # readouts/, schemas/ (shared contract fixtures)
SERVER = os.path.join(REPO, "06-optional", "mcp-server", "server.py")


def run(msgs, data):
    env = dict(os.environ, OTM_DATA_DIR=data)
    env.pop("OTM_CONFIG", None)
    inp = "".join(json.dumps(m) + "\n" for m in msgs)
    out = subprocess.run([sys.executable, SERVER], input=inp, capture_output=True, text=True, env=env, timeout=30)
    return [json.loads(l) for l in out.stdout.splitlines()]


def call(i, name, **args):
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": args}}


class TestMcp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = tempfile.mkdtemp()
        for f in ("analysis.json", "impact_summary.json", "decisions.jsonl"):
            shutil.copy(os.path.join(FIX, "readouts", f), cls.data)
        shutil.copy(os.path.join(FIX, "schemas", "sessions.jsonl"), cls.data)
        with open(os.path.join(cls.data, "analysis.json")) as f:
            cls.analysis = json.load(f)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.data)

    def tool(self, name, **args):
        r = run([call(1, name, **args)], self.data)[0]["result"]
        return r["isError"], (r["content"][0]["text"] if r["isError"] else json.loads(r["content"][0]["text"]))

    def test_handshake_and_list(self):
        rs = run([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                  {"jsonrpc": "2.0", "method": "notifications/initialized"},
                  {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                  {"jsonrpc": "2.0", "id": 3, "method": "nope"}], self.data)
        self.assertEqual([r["id"] for r in rs], [1, 2, 3])  # notification gets no reply
        self.assertIn("tools", rs[0]["result"]["capabilities"])
        names = {t["name"] for t in rs[1]["result"]["tools"]}
        self.assertEqual(names, {"summary", "outliers", "metric", "session", "impact", "decisions", "recommendations", "usage_breakdown", "coverage"})
        self.assertEqual(rs[2]["error"]["code"], -32601)

    def test_summary_matches_analysis(self):
        err, s = self.tool("summary")
        self.assertFalse(err)
        self.assertEqual(s["totals"], self.analysis["totals"])
        self.assertEqual(s["by_harness"], self.analysis["by"]["harness"])

    def test_metric_outliers_pagination(self):
        _, m = self.tool("metric", id="M-cache-hit-rate")
        self.assertEqual((m["total"], m["items"][0]["value"]), (1, 0.763359))
        _, m = self.tool("metric", limit=1)
        self.assertEqual((m["total"], len(m["items"]), m["next_offset"]), (2, 1, 1))
        _, m = self.tool("metric", limit=10 ** 6)
        self.assertEqual(m["next_offset"], None)
        _, o = self.tool("outliers", group="claude-code")
        self.assertEqual(o["items"][0]["session_id"], "s-0001")

    def test_session_never_leaks_repo(self):
        _, s = self.tool("session", session_id="s-0001")
        self.assertEqual(s["cost"]["total"], 0.01725)
        _, lst = self.tool("session")
        for r in [s] + lst["items"]:
            self.assertNotIn("repo", r)
        self.assertNotIn("/home/", json.dumps([s, lst]))
        err, _ = self.tool("session", session_id="missing")
        self.assertTrue(err)

    def test_impact_decisions_coverage(self):
        _, im = self.tool("impact", by="harness")
        self.assertEqual((im["unlinked_cost"], im["items"][0]["harness"]), (0.000125, "claude-code"))
        _, d = self.tool("decisions", point="outlier_explanation")
        self.assertEqual(d["items"][0]["choice"], "large_context")
        _, c = self.tool("coverage", harness="codex")
        self.assertEqual(c["codex"]["sessions"], 1)

    def test_budget_compact_recommendations_window(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("srv", SERVER)
        srv = importlib.util.module_from_spec(spec); spec.loader.exec_module(srv)
        big = srv.fit({"items": [{"x": "y" * 400}] * 50, "total": 60, "offset": 0, "next_offset": 50})
        self.assertLessEqual(srv.size_tokens(big), srv.MAX_RESPONSE_TOKENS)
        self.assertEqual(big["next_offset"], len(big["items"]))
        _, d = self.tool("decisions")
        self.assertTrue(all(set(r) <= {"ts", "point", "subject", "choice", "p"} for r in d["items"]))
        _, o = self.tool("outliers")
        self.assertTrue(all("session_ids" not in r for r in o["items"]))
        _, r = self.tool("recommendations")
        self.assertEqual(r["total"], len(self.analysis.get("recommendations", [])))
        days = self.analysis["by"].get("day", [])
        if days:
            _, s = self.tool("summary", days=1)
            last = max(days, key=lambda d: d["day"])
            self.assertEqual((s["window"]["since"], s["window"]["days"]), (last["day"], 1))
        self.assertIn("error", run([call(1, "summary", since="last week")], self.data)[0])
        self.assertIn("error", run([call(1, "decisions", detail="yes")], self.data)[0])

    def test_errors(self):
        bad = [call(1, "summary", bogus=1), call(2, "impact", by="model"), call(3, "metric", limit=0),
               call(4, "coverage", harness=["x"]), call(5, "metric", limit=1e400),
               {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": [1]},
               {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "summary", "arguments": [1]}},
               {"jsonrpc": "2.0", "id": 8}, {"jsonrpc": "2.0", "id": 9, "method": "ping"}]
        rs = run(bad, self.data)  # server survives every bad request
        self.assertEqual([r.get("error", {}).get("code") for r in rs],
                         [-32602] * 7 + [-32600, None])

    def test_internal_error_keeps_serving(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "sessions.jsonl"), "w") as f:
            f.write('{"session_id": "x", "cost": null}\n{"session_id": "y", "cost": {"total": 1}}\n')
        with open(os.path.join(d, "analysis.json"), "w") as f:
            f.write('{"by": {"model": [%s]}, "outliers": [1]}' % ",".join(['{"name": "m"}'] * 60))
        rs = run([call(1, "session"), call(2, "coverage"), call(3, "summary"), call(4, "outliers", metric="x"),
                  {"jsonrpc": "2.0", "id": 5, "method": "ping"}], d)
        shutil.rmtree(d)
        lst = json.loads(rs[0]["result"]["content"][0]["text"])
        self.assertEqual([(i["session_id"], i["cost"]) for i in lst["items"]], [("y", 1), ("x", None)])
        summ = json.loads(rs[2]["result"]["content"][0]["text"])
        self.assertEqual((len(summ["by_model"]), summ["truncated"]), (10, {"model": 60}))
        self.assertEqual(rs[3]["error"]["code"], -32603)  # outlier record is not an object
        self.assertEqual(rs[4]["result"], {})

    def test_protocol_version(self):
        init = lambda v: {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": v}}
        rs = run([init("2025-03-26"), init("1999-01-01")], self.data)
        self.assertEqual([r["result"]["protocolVersion"] for r in rs], ["2025-03-26", "2025-06-18"])

    def test_missing_file(self):
        empty = tempfile.mkdtemp()
        r = run([call(1, "summary")], empty)[0]["result"]
        shutil.rmtree(empty)
        self.assertTrue(r["isError"])
        self.assertIn("analysis.json", r["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
