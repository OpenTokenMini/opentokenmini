"""collector: make_record (N-redact, N-identity, N-undecoded, N-pb), unzip limit, files sink, normalize on fixtures."""
import hashlib, base64, gzip, importlib.util, json, os, struct, sys, tempfile, unittest

import pathlib  # numbered stage dirs aren't importable: find the repo, use 02-measure/ for imports
REPO = str(next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir()))
MEASURE = os.path.join(REPO, "02-measure")
sys.path.insert(0, MEASURE)


def _load(name):  # by path: every stage has a connectors.py, bare imports collide
    spec = importlib.util.spec_from_file_location("test_collector_" + name, os.path.join(MEASURE, "collector", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


collector, normalize = _load("collector"), _load("normalize")
connectors, protowire = collector.connectors, collector.protowire
from schemas.check import validate

FIX = os.path.join(MEASURE, "tests", "fixtures", "collector", "otel")


def kv(k, s):
    return {"key": k, "value": {"stringValue": s}}


def body(attrs, svc="claude-code"):
    return {"resourceLogs": [{"resource": {"attributes": [kv("service.name", svc)]},
                              "scopeLogs": [{"logRecords": [{"attributes": attrs}]}]}]}


def pb(field, wt, payload):  # protobuf field encoder for the N-pb test
    tag = bytes([field << 3 | wt])
    return tag + (bytes([len(payload)]) + payload if wt == 2 else payload)


class Collector(unittest.TestCase):
    def test_redact_and_hash(self):  # N-redact, N-identity worked example
        b = json.dumps(body([kv("prompt", "hello"), kv("user.email", "a@b.c"), kv("user.id", "0123456789ab"),
                             kv("model", "m")])).encode()
        r = collector.make_record("/v1/logs", "application/json", b)
        a = {x["key"]: x["value"]["stringValue"] for x in r["data"]["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["attributes"]}
        self.assertEqual(a["prompt"], "[redacted len=24]")  # len(json.dumps(original AnyValue))
        self.assertEqual(a["user.email"], "d648b243a3e8")  # sha256("a@b.c")[:12]
        self.assertEqual(a["user.id"], "0123456789ab")  # already hashed: kept
        self.assertEqual(a["model"], "m")
        self.assertEqual(r["harness_hint"], "claude-code")
        self.assertEqual(validate(r, "raw"), [])

    def test_no_hash_when_disabled(self):  # hash_identity=False keeps IDENTITY keys, not N-pii ones
        b = json.dumps(body([kv("host.name", "rig"), kv("user.email", "a@b.c")])).encode()
        r = collector.make_record("/v1/logs", "application/json", b, hash_identity=False)
        self.assertIn('"rig"', json.dumps(r))
        self.assertNotIn("a@b.c", json.dumps(r))

    def test_pii_at_write(self):  # N-pii: emails and /home/<user> gone from the stored record, identity still joinable
        email, home = "owner.name@example.org", "/home/someuser"
        lr = {"attributes": [kv("user.email", email), kv("user.account_uuid", "6f1c-uuid"), kv("note", "by " + email),
                             kv("cwd", home + "/projects/x"), {"key": "list", "value": {"arrayValue": {"values": [
                                 {"stringValue": home + "/a"}]}}}],
              "body": {"stringValue": f"user {email} opened {home}/f.py"}}
        b = json.dumps({"resourceLogs": [{"resource": {"attributes": [kv("service.name", "claude-code")]},
                                          "scopeLogs": [{"logRecords": [lr]}]}]}).encode()
        with tempfile.TemporaryDirectory() as d:
            connectors.files(collector.make_record("/v1/logs", "application/json", b, hash_identity=False), {"data_dir": d})
            od = os.path.join(d, "otel")
            stored = "".join(open(os.path.join(od, f)).read() for f in os.listdir(od))
        self.assertNotIn("@example.org", stored)
        self.assertNotIn("/home/", stored)
        self.assertIn("~/projects/x", stored)
        h = collector.hash_id(email)
        self.assertIn(h, stored)
        self.assertEqual(normalize.user_hash({"user.email": h}), normalize.user_hash({"user.email": email}))

    def test_undecoded_dropped(self):  # N-undecoded: body dropped, summary kept, warned
        msgs, body_ = [], b"\x01secret prompt"
        r = collector.make_record("/v1/logs", "application/json", body_, warn=msgs.append)
        self.assertNotIn("data_b64", r)
        self.assertNotIn("data", r)
        self.assertEqual(r["undecoded"], {"bytes": 14, "sha256": hashlib.sha256(body_).hexdigest(),
                                          "content_type": "application/json", "reason": "not_json_object"})
        self.assertNotIn("secret", json.dumps(r))
        self.assertEqual(len(msgs), 1)
        self.assertEqual(validate(r, "raw"), [])

    def test_undecoded_opt_in(self):  # KEEP_RAW_UNDECODED = True restores data_b64
        collector.KEEP_RAW_UNDECODED = True
        try:
            r = collector.make_record("/v1/logs", "application/json", b"\x01\x02")
        finally:
            collector.KEEP_RAW_UNDECODED = False
        self.assertEqual(r["data_b64"], "AQI=")
        self.assertNotIn("undecoded", r)
        self.assertEqual(validate(r, "raw"), [])

    def test_protowire(self):  # N-pb: stdlib decode then scrub, same as JSON path
        key = lambda k, s: pb(1, 2, k.encode()) + pb(2, 2, pb(1, 2, s.encode()))
        res = pb(1, 2, pb(1, 2, key("service.name", "codex")))
        rec = (pb(1, 1, struct.pack("<Q", 5)) + pb(9, 2, b"\xab" * 4) + pb(6, 2, key("prompt", "secret"))
               + pb(6, 2, pb(1, 2, b"n") + pb(2, 2, pb(3, 0, b"\x07"))))
        msg = pb(1, 2, res + pb(2, 2, pb(2, 2, rec)))
        d = protowire.decode(msg, protowire.REQUEST["logs"])
        lr = d["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
        self.assertEqual((lr["timeUnixNano"], lr["traceId"]), ("5", "abababab"))
        self.assertEqual(lr["attributes"][1], {"key": "n", "value": {"intValue": "7"}})
        saved, collector.PB = collector.PB, {}
        try:
            r = collector.make_record("/v1/logs", "application/x-protobuf", msg)
        finally:
            collector.PB = saved
        self.assertNotIn("secret", json.dumps(r))
        self.assertEqual(r["harness_hint"], "codex")
        with self.assertRaises((ValueError, IndexError)):
            protowire.decode(b"\x0a\x09ab", protowire.REQUEST["logs"])  # truncated length

    def test_unzip_limit(self):  # N-body-limit applies after decompression
        saved, collector.MAX_BODY = collector.MAX_BODY, 100
        try:
            self.assertEqual(collector.unzip(gzip.compress(b"x" * 100)), b"x" * 100)
            self.assertIsNone(collector.unzip(gzip.compress(b"x" * 101)))
        finally:
            collector.MAX_BODY = saved

    def test_files_sink(self):  # N-raw-file: UTC day of recv_ts
        with tempfile.TemporaryDirectory() as d:
            rec = {"v": 1, "recv_ts": "2026-01-02T23:59:59.000000Z", "path": "/v1/traces", "content_type": "",
                   "harness_hint": None, "data": {}}
            connectors.files(rec, {"data_dir": d})
            connectors.files(rec, {"data_dir": d})
            with open(os.path.join(d, "otel", "traces-2026-01-02.jsonl")) as f:
                self.assertEqual(len(f.readlines()), 2)


class Normalize(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ev = normalize.normalize(FIX)
        cls.by = {(e["harness"], e["kind"], bool(e["error"])): e for e in cls.ev}

    def test_counts_and_valid(self):  # N-dedup: legacy line repeats claude events; N-raw-read skips 2 lines
        self.assertEqual(len(self.ev), 8)
        self.assertEqual(normalize.raw_records.skipped, 2)
        for e in self.ev:
            self.assertEqual(validate(e, "event"), [])

    def test_claude(self):  # N-claude
        e = self.by[("claude-code", "api_call", False)]
        self.assertEqual(e["tokens"], {"input": 10, "output": 20, "cache_read": 300, "cache_write": 40, "reasoning": 0})
        self.assertEqual((e["cost"]["total"], e["cost_basis"], e["subagent"]), (0.5, "reported_total_allocated", True))
        self.assertEqual(self.by[("claude-code", "tool_decision", False)]["decision"], "reject")
        self.assertEqual(e["cache_split"], "unknown")  # N-claude-ttl: reported 0.5 beats the all-1h bound, kept

    def test_claude_ttl_upper(self):  # N-claude-ttl: cost_usd below the all-1h list price -> list_price at 1h rate
        p = normalize.load_prices()
        e = normalize.base("api_call", "claude-code", "t", "s", {})
        e.update(model="claude-sonnet-4", tokens=normalize.make_tokens(0, 0, 0, 1_000_000))
        e = normalize.ttl_upper(normalize.priced(e, p, 3.75), p)
        self.assertEqual((e["cost"]["total"], e["cost_basis"], e["cache_split"]), (6.0, "list_price", "unknown"))

    def test_claude_agent_and_split(self):  # N-claude-agent, C-cache-ttl: query_source/agent.name kept, 5m/1h split read
        p = normalize.load_prices()
        a = {"event.name": "api_request", "session.id": "s-x", "event.timestamp": "2026-10-01T10:00:00Z",
             "model": "claude-opus-5-5", "input_tokens": "1000", "output_tokens": "100", "cache_read_tokens": "0",
             "cache_creation_tokens": "3000", "cache_creation_5m_tokens": "1000", "cache_creation_1h_tokens": "2000",
             "cost_usd": "0.027", "query_source": "agent:builtin:Explore", "agent.name": "Explore"}
        e = normalize.claude_log({}, a, p)
        self.assertEqual(validate(e, "event"), [])
        self.assertEqual((e["query_source"], e["agent_name"], e["subagent"]), ("agent:builtin:Explore", "Explore", True))
        self.assertEqual((e["tokens"]["cache_write_5m"], e["tokens"]["cache_write_1h"], e["tokens"]["cache_write"]), (1000, 2000, 3000))
        self.assertNotIn("cache_split", e)  # split known: no N-claude-ttl upper bound
        self.assertAlmostEqual(e["cost"]["total"], 0.027)
        # list price with the fitted opus-5-5 rates equals the reported cost_usd: 1000*4 + 100*20 + 1000*5 + 2000*8 per M
        self.assertAlmostEqual(normalize.list_cost(e["tokens"], normalize.price_for(e["model"], p))["total"], 0.027)
        a2 = {k: v for k, v in a.items() if k not in ("query_source", "agent.name")}
        e2 = normalize.claude_log({}, a2, p)
        self.assertEqual((e2["query_source"], e2["agent_name"], e2["subagent"]), (None, None, False))
        self.assertEqual(validate(e2, "event"), [])

    def test_codex_prewarm(self):  # N-codex-prewarm: 0-output, no-ttft response.completed dropped
        self.assertEqual(sum(e["harness"] == "codex" and e["kind"] == "api_call" for e in self.ev), 2)

    def test_codex(self):  # N-codex: input includes cache, output includes reasoning
        e = self.by[("codex", "api_call", False)]
        self.assertEqual(e["tokens"], {"input": 200, "output": 20, "cache_read": 800, "cache_write": 0, "reasoning": 30})
        self.assertEqual(self.by[("codex", "api_call", True)]["error"], "rate limited")

    def test_pi(self):  # N-pi: disjoint tokens, project from cwd
        e = self.by[("pi", "api_call", False)]
        self.assertEqual(e["tokens"], {"input": 5, "output": 6, "cache_read": 7, "cache_write": 8, "reasoning": 0})
        self.assertEqual((e["project"], e["tools"], e["cost"]["total"]), ("proj", ["read", "bash"], 0.01))

    def test_opencode(self):  # N-opencode: AI SDK usage inclusive
        e = self.by[("opencode", "api_call", False)]
        self.assertEqual(e["tokens"], {"input": 40, "output": 30, "cache_read": 60, "cache_write": 0, "reasoning": 10})
        self.assertEqual((e["session_id"], e["duration_ms"], e["request_id"]), ("s-oc", 1000.0, None))


if __name__ == "__main__":
    unittest.main()
