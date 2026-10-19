"""analyze: fixture tests/fixtures/analyze/events (3 harnesses, otel+transcript duplicates, planted outlier s-cc-10)."""
import json, os, re, sys, unittest
import pathlib  # numbered stage dirs aren't importable: find the repo, use 02-measure/ for imports
REPO = str(next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir()))
MEASURE = os.path.join(REPO, "02-measure")
sys.path.insert(0, MEASURE)
import importlib.util
_spec = importlib.util.spec_from_file_location("analyze_main", os.path.join(REPO, "03-analyze", "analyze", "analyze.py"))
analyze = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(analyze)
outliers, connectors = analyze.outliers, analyze.connectors
from schemas.config import load_config
from schemas.check import validate

FIX = os.path.join(REPO, "03-analyze", "tests", "fixtures", "analyze", "events")


def run(**kw):
    cfg = load_config()
    cfg["analyze"]["_events_dir"] = FIX
    return analyze.analyze(connectors.files_source(cfg), cfg, now=analyze.parse_ts("2026-10-05T00:00:00Z"), **kw)


class TestAnalyze(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sessions, cls.a = run()

    def m(self, mid, group=None):
        return next(x["value"] for x in self.a["metrics"] if x["id"] == mid and x["group"] == group)

    def test_schema_valid(self):
        self.assertEqual(validate(self.a, "analysis"), [])
        for s in self.sessions:
            self.assertEqual(validate(s, "session"), [])

    def test_totals_and_sums(self):            # M-totals: totals = sum sessions = sum deduped events
        t = self.a["totals"]
        self.assertAlmostEqual(t["cost"]["total"], 4.55, places=9)
        self.assertEqual((t["calls"], t["sessions"], t["turns"], t["projects"]), (28, 15, 15, 3))
        self.assertAlmostEqual(sum(s["cost"]["total"] for s in self.sessions), t["cost"]["total"], places=9)
        self.assertAlmostEqual(t["subagent_cost"], 0.14, places=9)

    def test_dedup(self):                      # M-dedup worked example: 10 prompts + 20 id matches + 1 null-id call
        c = self.a["coverage"]["claude-code"]
        self.assertEqual((c["duplicates_dropped"], c["events"], c["sessions"]), (31, 32, 11))
        s2 = next(s for s in self.sessions if s["session_id"] == "s-cc-02")
        self.assertEqual((s2["calls"], s2["sources"]), (2, ["otel"]))
        s11 = next(s for s in self.sessions if s["session_id"] == "s-cc-11")
        self.assertEqual(s11["sources"], ["transcript"])
        self.assertEqual(self.a["coverage"]["antigravity"]["reason"], "no events")
        self.assertEqual(self.a["coverage"]["opencode"]["unpriced_calls"], 1)

    def test_dedup_ttl_merge(self):            # M-dedup-ttl: otel identity kept, transcript TTL tokens/cost taken
        ev = lambda src, **kw: {"source": src, "harness": "claude-code", "session_id": "s", "kind": "api_call",
                                "request_id": "r1", "_t": 0.0, **kw}
        o = ev("otel", tokens={"cache_write": 10}, cost={"total": 1.0}, cost_basis="list_price", cache_split="unknown",
               duration_ms=5.0)
        t = ev("transcript", tokens={"cache_write": 10, "cache_write_5m": 0, "cache_write_1h": 10},
               cost={"total": 2.0}, cost_basis="list_price", duration_ms=None)
        kept, _ = analyze.dedup([o, t], "otel")
        self.assertEqual(len(kept), 1)
        k = kept[0]
        self.assertEqual((k["source"], k["duration_ms"], k["cost"]["total"], k["tokens"]["cache_write_1h"]), ("otel", 5.0, 2.0, 10))
        self.assertNotIn("cache_split", k)

    def test_session(self):                    # M-session worked example
        s = self.sessions[0]
        self.assertEqual((s["session_id"], s["active_minutes"], s["cost_basis"]), ("s-cc-01", 1.1667, "reported"))

    def test_metrics(self):
        self.assertAlmostEqual(self.m("M-cost-share-output"), 0.5)
        self.assertAlmostEqual(self.m("M-cache-hit-rate"), 1000 / 1100)
        self.assertAlmostEqual(self.m("M-cost-per-call"), 4.55 / 28)
        self.assertAlmostEqual(self.m("M-calls-per-turn"), 28 / 15)
        self.assertAlmostEqual(self.m("M-session-cost-median"), 0.24)
        self.assertAlmostEqual(self.m("M-session-cost-p90"), 0.29)
        self.assertAlmostEqual(self.m("M-mcp-error-rate"), 1.0)
        self.assertAlmostEqual(self.m("M-approval-rate", "codex"), 0.5)
        self.assertIsNone(self.m("M-mcp-error-rate", "codex"))
        self.assertAlmostEqual(self.a["by"]["tool"][0]["cost"], 4.36)

    def test_outlier(self):                    # O-robust-z worked example
        o = [x for x in self.a["outliers"] if x["flagged"]]
        self.assertEqual(len(o), 1)
        self.assertEqual((o[0]["session_id"], o[0]["baseline"], o[0]["score"]), ("s-cc-10", 0.25, 16.821))  # O-log-scale
        lg = outliers.find("M-x", None, [(str(i), 1.0 + i % 3) for i in range(9)] + [("big", 30.0), ("z", 0.0)], log=True)
        self.assertEqual([(x["session_id"], x["n"]) for x in lg], [("big", 10)])  # O-log-scale: 0 left out
        self.assertEqual(outliers.find("M-x", None, [("a", 1.0)] * 3), [])          # no spread
        small = outliers.find("M-x", None, [("a", 1), ("b", 1.1), ("c", 0.9), ("d", 50)])
        self.assertEqual([(x["session_id"], x["flagged"]) for x in small], [("d", False)])  # n < MIN_SAMPLE

    def test_spread_floor(self):               # O-spread-floor: scale >= MIN_REL_SPREAD * |median|
        base = [(f"s{i:02d}", 4.0 + i % 2) for i in range(20)]             # with near/far: median 5, MAD 1
        ids = lambda o: [x["session_id"] for x in o]
        near, far = base + [("near", 11.0)], base + [("far", 20.0)]
        self.assertEqual(ids(outliers.find("M-x", "g", near)), ["near"])      # no floor: 2.2x median flagged
        self.assertEqual(ids(outliers.find("M-x", "g", near, floor=True)), [])  # neg: under ~2.75x median
        self.assertEqual(ids(outliers.find("M-x", "g", far, floor=True)), ["far"])  # pos: 4x median
        self.assertEqual(ids(outliers.find("M-x", "g", far, log=True, floor=True)), ["far"])  # log ignores floor
        self.assertTrue(analyze.CAT["M-session-calls-per-turn"].get("spread_floor"))
        self.assertFalse(analyze.CAT["M-session-cache-hit-rate"].get("spread_floor"))

    def test_model_group(self):                # O-model-group: per (harness, main model), small groups -> harness
        def sess(i, model, cost):
            return {"session_id": f"{model}-{i:02d}", "harness": "h", "calls": 10, "turns": 2, "models": {model: cost},
                    "cost": {"total": cost}, "tokens": {"input": 1, "cache_read": 9, "cache_write": 0}}
        n = analyze.MIN_GROUP
        ss = [sess(i, "cheap", 0.01 * (1 + 0.1 * (i % 3))) for i in range(3 * n)] + [sess(i, "big", 1.0 * (1 + i % 3)) for i in range(n)]
        ss += [sess(0, "rare", 50.0)]
        o = [x for x in analyze.find_outliers(ss, ["h"]) if x["metric"] == "M-session-cost-per-call"]
        self.assertEqual([(x["group"], x["session_id"]) for x in o], [("h", "rare-00")])   # cheap/big: no flags
        self.assertEqual(o[0]["n"], 4 * n + 1)
        flat = outliers.find("M-session-cost-per-call", "h", [(x["session_id"], x["cost"]["total"] / 10) for x in ss], log=True)
        self.assertEqual(len(flat), n + 1)                         # harness-only baseline flags every "big" session
        self.assertEqual(analyze.main_model({"models": {"b": 1.0, "a": 1.0, "c": 0.5}}), "a")

    def test_spec_ids(self):                   # every metric id is in the catalog and in METHOD.md
        method = open(os.path.join(REPO, "03-analyze", "analyze", "METHOD.md")).read()
        cat = {m["id"] for m in analyze.CATALOG["metrics"]}
        for x in self.a["metrics"] + self.a["outliers"]:
            self.assertIn(x.get("id", x.get("metric")), cat)
        for mid in cat:
            self.assertRegex(method, re.escape(mid) + r"\b")

    def test_deterministic_and_filters(self):
        self.assertEqual(json.dumps(run()), json.dumps((self.sessions, self.a)))
        s, a = run(harness="codex")
        self.assertEqual((a["totals"]["sessions"], list(a["coverage"])), (3, ["codex"]))
        s, a = run(days=2.5)                   # since 2026-10-02T12:00Z
        self.assertEqual(a["totals"]["sessions"], 3)


if __name__ == "__main__":
    unittest.main()
