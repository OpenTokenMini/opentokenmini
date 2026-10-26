import copy, json, os, subprocess, sys, tempfile, unittest

import pathlib  # numbered stage dirs aren't importable: find the repo, use 02-measure/ for imports
REPO = str(next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir()))
MEASURE = os.path.join(REPO, "02-measure")
sys.path.insert(0, MEASURE)
from schemas.check import check_file, validate
from schemas.config import DEFAULTS, connector, data_dir, load_config
from schemas.cost import allocate, event_cost, load_prices, make_tokens, price_for, worst_basis

FIX = os.path.join(MEASURE, "tests", "fixtures")
FILES = {"schemas/events.jsonl": "event", "schemas/raw.jsonl": "raw", "schemas/sessions.jsonl": "session",
         "schemas/decisions.jsonl": "decision", "schemas/impact.jsonl": "impact",
         "readouts/analysis.json": "analysis", "readouts/impact_summary.json": "impact_summary",
         "readouts/decisions.jsonl": "decision"}


def first(rel):
    with open(os.path.join(FIX, rel)) as f:
        return json.loads(f.readline()) if rel.endswith(".jsonl") else json.load(f)


class Fixtures(unittest.TestCase):
    def test_fixtures_valid(self):
        for rel, name in FILES.items():
            self.assertEqual(check_file(os.path.join(FIX, rel), name), [], rel)

    def test_cli_rejects_broken_copy(self):
        ev = first("schemas/events.jsonl")
        ev["kind"], ev["tokens"], ev["cost"] = "api_call", make_tokens(input=10), {"input": 1, "output": 0, "cache_read": 0, "cache_write": 0, "total": 2}
        with tempfile.TemporaryDirectory() as d:
            os.mkdir(os.path.join(d, "events"))
            p = os.path.join(d, "events", "otel.jsonl")
            with open(p, "w") as f:
                f.write(json.dumps(ev) + "\n")
            r = subprocess.run([sys.executable, os.path.join(MEASURE, "schemas", "check.py"), p], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            self.assertIn("C-sum", r.stdout)
            ok = subprocess.run([sys.executable, os.path.join(MEASURE, "schemas", "check.py"),
                                 os.path.join(FIX, "schemas", "events.jsonl")], capture_output=True)
            self.assertEqual(ok.returncode, 0)


class Broken(unittest.TestCase):
    def broken(self, rel, name, mutate, expect):
        obj = copy.deepcopy(first(rel))
        mutate(obj)
        errs = validate(obj, name)
        self.assertTrue(any(expect in e for e in errs), errs)

    def test_event(self):
        r = "schemas/events.jsonl"
        self.broken(r, "event", lambda o: o.pop("session_id"), "missing session_id")
        self.broken(r, "event", lambda o: o.update(harness="claude_code"), "not in")
        self.broken(r, "event", lambda o: o.update(text="hello"), "unexpected key text")
        self.broken(r, "event", lambda o: o["tokens"].update(input=-1), "< 0")
        self.broken(r, "event", lambda o: o["tokens"].update(input=1.5), "expected integer")
        self.broken(r, "event", lambda o: o.update(decision="accept"), "S-event-kind")
        self.broken(r, "event", lambda o: o.update(ts="2026-10-01 10:00"), "does not match")

    def test_session_analysis_decision_impact(self):
        self.broken("schemas/sessions.jsonl", "session", lambda o: o["cost"].update(total=1.0), "C-sum")
        self.broken("schemas/sessions.jsonl", "session", lambda o: o.update(end="2026-09-01T00:00:00Z"), "S-session-order")
        self.broken("schemas/sessions.jsonl", "session", lambda o: o.update(cost_basis="guess"), "not in")
        self.broken("readouts/analysis.json", "analysis", lambda o: o["totals"]["cost"].update(output=9.0), "C-sum")
        self.broken("readouts/analysis.json", "analysis", lambda o: o["metrics"][0].update(id="cache_hit"), "does not match")
        self.broken("schemas/decisions.jsonl", "decision", lambda o: o.update(choice="maybe"), "S-decision-choice")
        self.broken("schemas/impact.jsonl", "impact", lambda o: o.update(link="guess"), "not in")
        self.broken("readouts/impact_summary.json", "impact_summary", lambda o: o["by_harness"][0].pop("harness"), "missing harness")
        self.broken("schemas/raw.jsonl", "raw", lambda o: o.pop("recv_ts"), "anyOf")


class Semantic(unittest.TestCase):
    """METHOD.md S-* worked examples and edge cases."""
    events = [json.loads(l) for l in open(os.path.join(FIX, "schemas", "events.jsonl"))]

    def ev(self, kind):
        return copy.deepcopy(next(e for e in self.events if e["kind"] == kind))

    def errs(self, obj, name, expect):
        e = validate(obj, name)
        self.assertTrue(any(expect in x for x in e) if expect else not e, e)

    def test_s_event_kind(self):
        for kind in ("user_prompt", "tool_decision"):
            o = self.ev(kind)
            self.errs(o, "event", None)
            o["tokens"]["input"] = 5
            self.errs(o, "event", f"{kind} carries no tokens")
            o = self.ev(kind)
            o["cost"].update(input=0.5, total=0.5)
            self.errs(o, "event", f"{kind} carries no cost")
        o = self.ev("tool_decision")
        o["tool"] = None
        self.errs(o, "event", "needs tool and decision")
        o = self.ev("api_call")
        o["decision_source"] = "user"
        self.errs(o, "event", "only on tool_decision")

    def test_s_decision_choice(self):
        d = first("schemas/decisions.jsonl")
        self.errs(d, "decision", None)
        self.errs(dict(d, choice="unsure"), "decision", None)
        self.errs(dict(d, probabilities={**d["probabilities"], "zzz": 0.1}), "decision", "unknown options")
        self.errs(dict(d, probabilities={}), "decision", None)
        self.errs(dict(d, options={}, probabilities={}, choice="unsure"), "decision", None)
        self.errs(dict(d, options={}, probabilities={}), "decision", "neither an option")

    def test_s_session_order(self):
        s = first("schemas/sessions.jsonl")
        self.errs(dict(s, start="2026-10-01T12:00:00+02:00", end="2026-10-01T10:30:00Z"), "session", None)
        self.errs(dict(s, start="2026-10-01T10:30:00Z", end="2026-10-01T12:00:00+02:00"), "session", "S-session-order")
        self.errs(dict(s, start="2026-10-01T10:00:00Z", end="2026-10-01T10:00:00Z"), "session", None)
        self.errs(dict(s, start="2026-10-01T10:00:00.5Z", end="2026-10-01T10:00:00Z"), "session", "S-session-order")

    def test_s_raw_payload(self):
        r = first("schemas/raw.jsonl")
        if "v" not in r:
            r = {"v": 1, "recv_ts": "2026-10-01T10:00:00Z", "path": "/v1/logs", "content_type": "application/json",
                 "harness_hint": None, "data": {}}
        self.errs(r, "raw", None)
        no = {k: v for k, v in r.items() if k not in ("data", "data_b64", "undecoded")}
        self.errs(no, "raw", "S-raw-payload")
        self.errs(dict(no, data={}, data_b64="AA=="), "raw", "S-raw-payload")
        self.errs(dict(no, data_b64="AA=="), "raw", None)
        u = {"bytes": 2, "sha256": "00", "content_type": "x", "reason": "not_json_object"}
        self.errs(dict(no, undecoded=u), "raw", None)
        self.errs(dict(no, undecoded=u, data={}), "raw", "S-raw-payload")
        self.errs({"ts": 1790000000, "data": {}}, "raw", None)  # legacy line, rule not applied

    def test_const_strict(self):
        o = self.ev("api_call")
        self.errs(dict(o, v=1.0), "event", "expected 1")
        self.errs(dict(o, v=True), "event", "expected 1")


class Cost(unittest.TestCase):
    prices = load_prices()
    # METHOD.md C-tokens worked example
    tokens = make_tokens(input=13000, output=250, cache_read=10000, cache_write=2000, reasoning=50,
                         input_includes_cache=True, output_includes_reasoning=True)

    def close(self, got, want):
        for k, v in want.items():
            self.assertAlmostEqual(got[k], v, places=12, msg=k)

    def test_c_tokens(self):
        self.assertEqual(self.tokens, {"input": 1000, "output": 200, "cache_read": 10000, "cache_write": 2000, "reasoning": 50})
        self.assertEqual(make_tokens(input=5, cache_read=10, input_includes_cache=True)["input"], 0)

    def test_c_price_match(self):
        self.assertEqual(price_for("claude-opus-5-5", self.prices)["output"], 20)
        self.assertEqual(price_for("Claude-Opus-4-1", self.prices)["output"], 25)
        self.assertIsNone(price_for("mystery-1", self.prices))
        o, s = price_for("claude-opus-5-5", self.prices), price_for("claude-sonnet-5-5", self.prices)  # fitted / guess rows
        self.assertEqual([o[k] for k in ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")], [4, 20, 0.2, 5, 8])
        self.assertEqual([s[k] for k in ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")], [2, 10, 0.1, 2.5, 4])
        self.assertIn("guess", s["basis"])
        self.assertEqual(price_for("claude-sonnet-4-6", self.prices)["output"], 15)  # sonnet-5-5 does not shadow sonnet
        self.assertIsNone(price_for(None, self.prices))

    def test_c_list(self):
        c, basis = event_cost(self.tokens, "claude-sonnet-4", self.prices)
        self.assertEqual(basis, "list_price")
        self.close(c, {"input": 0.003, "output": 0.00375, "cache_read": 0.003, "cache_write": 0.0075, "total": 0.01725})

    def test_c_allocate(self):
        c, basis = event_cost(self.tokens, "claude-sonnet-4", self.prices, reported_total=0.0345)
        self.assertEqual(basis, "reported_total_allocated")
        self.close(c, {"input": 0.006, "output": 0.0075, "cache_read": 0.006, "cache_write": 0.015, "total": 0.0345})
        self.close(allocate(1.0, make_tokens(input=1, output=3), None), {"input": 0.25, "output": 0.75})
        self.close(allocate(1.0, make_tokens(), None), {"input": 1.0, "total": 1.0})

    def test_c_cost_reported_unknown(self):
        c, basis = event_cost(self.tokens, "x", self.prices, reported={"input": 0.1, "output": 0.2})
        self.assertEqual(basis, "reported")
        self.close(c, {"total": 0.3, "cache_read": 0.0})
        c, basis = event_cost(self.tokens, "mystery-1", self.prices)
        self.assertEqual((basis, c["total"]), ("unknown", 0.0))

    def test_c_cache_ttl(self):
        t = make_tokens(cache_write=3500, cache_write_5m=1000, cache_write_1h=2000)
        self.assertEqual((t["cache_write"], t["cache_write_5m"], t["cache_write_1h"]), (3500, 1000, 2000))
        c, _ = event_cost(t, "claude-sonnet-4", self.prices)
        self.close(c, {"cache_write": (500 * 3.75 + 1000 * 3.75 + 2000 * 6) / 1e6, "total": 0.017625})
        self.assertEqual(make_tokens(cache_write_1h=10)["cache_write"], 10)  # raised to the split sum
        self.assertNotIn("cache_write_5m", make_tokens(cache_write=5))
        c, _ = event_cost(make_tokens(cache_write=100, cache_write_1h=100), "gpt-5", self.prices)
        self.assertEqual(c["cache_write"], 0.0)  # no TTL price -> flat cache_write
        ev = [json.loads(l) for l in open(os.path.join(FIX, "schemas", "events.jsonl"))]
        api = next(e for e in ev if e["kind"] == "api_call")
        api["tokens"].update(cache_write_5m=0, cache_write_1h=api["tokens"]["cache_write"])
        self.assertEqual(validate(api, "event"), [])
        api["tokens"]["cache_write_5m"] = 1
        self.assertTrue(any("C-cache-ttl" in e for e in validate(api, "event")))

    def test_c_basis_worst(self):
        self.assertEqual(worst_basis(["reported", "list_price", "reported"]), "list_price")
        self.assertEqual(worst_basis([]), "unknown")


class Config(unittest.TestCase):
    def test_defaults_and_merge(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.json")
            with open(p, "w") as f:
                json.dump({"_comment": "x", "analyze": {"sink": "stdout"}, "readers": {"paths": {"codex": "/x"}}}, f)
            cfg = load_config(p)
            self.assertEqual(cfg["analyze"], {"source": "files", "sink": "stdout", "prefer_source": "otel"})
            self.assertEqual(cfg["readers"]["paths"], {"codex": "/x"})
            self.assertEqual(cfg["collector"], DEFAULTS["collector"])
            with open(p, "w") as f:
                json.dump({"readouts": {}}, f)
            self.assertRaises(ValueError, load_config, p)
            self.assertRaises(FileNotFoundError, load_config, os.path.join(d, "missing.json"))

    def test_types_and_comments(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.json")
            for bad in ({"collector": 5}, {"collector": {"port": "80"}}, {"collector": {"port": True}},
                        {"collector": {"hash_identity": 1}}, {"analyze": {"sink": None}}, {"readers": {"enabled": ["cursor"]}},
                        {"readers": {"paths": {"cursor": "/x"}}}, {"readers": {"paths": {"codex": 5}}}, {"impact": {"repos": [1]}}):
                with open(p, "w") as f:
                    json.dump(bad, f)
                self.assertRaises(ValueError, load_config, p)
            with open(p, "w") as f:
                json.dump({"collector": {"_note": "x", "port": 4318}, "readers": {"paths": {"_n": "x"}}, "data_dir": "/tmp/o"}, f)
            cfg = load_config(p)
            self.assertEqual((cfg["collector"]["port"], cfg["readers"]["paths"], cfg["data_dir"]), (4318, {}, "/tmp/o"))

    def test_example_loads(self):
        self.assertEqual(load_config(os.path.join(REPO, "01-deploy", "config.example.json"))["decide"]["vendor"], "jev")

    def test_data_dir_and_connector(self):
        old = os.environ.pop("OTM_DATA_DIR", None)
        try:
            self.assertEqual(data_dir({"data_dir": "/tmp/otm"}), "/tmp/otm")
            os.environ["OTM_DATA_DIR"] = "/tmp/otm-env"
            self.assertEqual(data_dir({"data_dir": "/tmp/otm"}), "/tmp/otm-env")
            os.environ["OTM_DATA_DIR"] = os.path.join(REPO, "data")
            self.assertRaises(ValueError, data_dir, {})
        finally:
            os.environ.pop("OTM_DATA_DIR", None)
            if old is not None:
                os.environ["OTM_DATA_DIR"] = old
        self.assertIs(connector({"files": len}, "files", "x.sink"), len)
        self.assertRaises(KeyError, connector, {"files": len}, "s3", "x.sink")


if __name__ == "__main__":
    unittest.main()
