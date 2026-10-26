import importlib.util, json, os, sys, tempfile, unittest

import pathlib  # numbered stage dirs aren't importable: find the repo, use 02-measure/ for imports
REPO = str(next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir()))
MEASURE = os.path.join(REPO, "02-measure")
FIX = os.path.join(REPO, "06-optional", "tests", "fixtures", "decide")
spec = importlib.util.spec_from_file_location("decide_stage", os.path.join(REPO, "06-optional", "decide", "decide.py"))
D = importlib.util.module_from_spec(spec); spec.loader.exec_module(D)
sys.path.insert(0, MEASURE)
from schemas.check import check_file


def cfg(vendor="stub", points=("outlier_explanation", "recommendation")):
    return {"decide": {"vendor": vendor, "points": list(points)}}


class TestDecide(unittest.TestCase):
    def test_pick_worked_example(self):  # D-pick
        self.assertEqual(D.pick({"a": 0.5, "b": 0.3, "c": 0.2}), "a")
        self.assertEqual(D.pick({"a": 0.45, "b": 0.35, "c": 0.2}), "unsure")
        self.assertEqual(D.pick({"yes": 0.9, "no": 0.1}), "yes")
        self.assertEqual(D.verdict(0.7), "suggest"); self.assertEqual(D.verdict(0.3), "skip"); self.assertEqual(D.verdict(0.5), "unsure")

    def test_run_cache_and_outputs(self):  # D-outlier-explanation, D-recommendation, D-commit-link, D-cache, D-apply
        with tempfile.TemporaryDirectory() as out:
            r = D.run(FIX, out, cfg())
            self.assertEqual((r["items"], r["asked"], r["unanswered"]), (13, 13, 0))
            self.assertEqual(D.run(FIX, out, cfg())["asked"], 0)
            self.assertEqual(check_file(os.path.join(out, "decisions.jsonl")), [])
            self.assertEqual(check_file(os.path.join(out, "analysis.decided.json"), "analysis"), [])
            a = json.load(open(os.path.join(out, "analysis.decided.json")))
            self.assertIn(a["outliers"][0]["decision"]["choice"], set(D.json.load(open(D.POINTS))["outlier_explanation"]["options"]) | {"unsure"})
            self.assertEqual(len(a["recommendations"]), 11)
            self.assertTrue(all(x["p_yes"] is not None for x in a["recommendations"]))
            links = [json.loads(l) for l in open(os.path.join(out, "decisions.jsonl")) if '"commit_link"' in l]
            self.assertEqual([x["subject"] for x in links], ["s-0002:a27c4f92"])
            self.assertNotIn("decision", json.load(open(os.path.join(FIX, "analysis.json")))["outliers"][0])

    def test_max_calls_then_resume(self):
        with tempfile.TemporaryDirectory() as out:
            self.assertEqual(D.run(FIX, out, cfg(), max_calls=5)["unanswered"], 8)
            self.assertEqual(D.run(FIX, out, cfg())["asked"], 8)

    def test_harness_filter(self):
        with tempfile.TemporaryDirectory() as out:
            self.assertEqual(D.run(FIX, out, cfg(), harness="codex", dry=True)["items"], 7)  # 6 recs + 1 commit_link

    def test_outlier_model_facts(self):  # D-outlier-model
        P = D._load("decision_points")
        o = {"metric": "M-session-cost-per-call", "group": "claude-code", "value": 0.196, "baseline": 0.0004, "score": 9.0, "n": 900, "session_id": "s1"}
        t = {"input": 1, "output": 1, "cache_read": 1, "cache_write": 1, "reasoning": 0}
        s = {"harness": "claude-code", "cost": {"total": 28.5, "input": 0, "output": 1, "cache_read": 20, "cache_write": 7.5}, "calls": 145, "turns": 41,
             "errors": 0, "retries": 0, "active_minutes": 30, "tokens": t, "models": {"claude-fable-5-1": 28.44, "claude-haiku-4-5": 0.06}}
        f = next(P.outliers({"outliers": [o]}, {"s1": s}, {"question": "q", "options": [], "kind": "choice"}))[1]["facts"]
        self.assertEqual((f["baseline"], f["main_model"], f["main_model_price_tier"]), ("harness_fallback", "claude-fable-5-1", "premium"))
        f = next(P.outliers({"outliers": [dict(o, group="claude-code/claude-haiku-4-5")]}, {}, {"question": "", "options": [], "kind": "choice"}))[1]["facts"]
        self.assertEqual(f["baseline"], "model"); self.assertNotIn("main_model", f)

    def test_intent_refused(self):
        with tempfile.TemporaryDirectory() as out, self.assertRaises(SystemExit):
            D.run(FIX, out, cfg(points=("intent",)))

    def test_jev_batch_body_and_ledger(self):
        sent = []

        def fake_post(url, body, headers=None):
            sent.append(body)
            ans = {}
            for q, x in body["questions"].items():
                ans[q] = {"type": "noul", "noul": 0.8} if x["type"] == "noul" else \
                    {"type": "choice", "probabilities": {k: 1 / len(x["criteria"]) for k in x["criteria"]}}
            return {"answers": ans}
        old, D.connectors.post = D.connectors.post, fake_post
        os.environ["TYPESAFE_API_KEY"] = os.environ.get("TYPESAFE_API_KEY", "test")
        try:
            with tempfile.TemporaryDirectory() as out:
                os.environ[D.LEDGER_ENV] = os.path.join(out, "ledger.jsonl")
                D.run(FIX, out, cfg("jev"))
                self.assertEqual(sum(len(b["questions"]) for b in sent), 13)
                self.assertEqual(len(sent), 5)  # outlier, recs claude-code, R1 codex (own evidence), recs codex, commit_link
                self.assertEqual(sent[0]["model"], "jev-latest")
                led = {x["agent"]: x["n"] for x in map(json.loads, open(os.environ[D.LEDGER_ENV]))}
                self.assertEqual(led, {"decide": 12, "impact": 1})
        finally:
            D.connectors.post = old
            os.environ.pop(D.LEDGER_ENV, None)


if __name__ == "__main__":
    unittest.main()
