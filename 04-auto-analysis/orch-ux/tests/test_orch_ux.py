"""orch_ux: synthetic transcripts in a temp dir, heuristics only (no network); checks METHOD.md U-ex."""
import contextlib, importlib.util, io, json, os, tempfile, unittest
from datetime import datetime, timezone

import pathlib
REPO = str(next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir()))
ENTRY = os.path.join(REPO, "04-auto-analysis", "orch-ux", "orch_ux.py")
_spec = importlib.util.spec_from_file_location("orch_ux_main", ENTRY)
ux = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ux)


def T(m):
    return f"2026-10-02T10:{m:02d}:00Z"


def human(text, m, **kw):
    return {"type": "user", "timestamp": T(m), "message": {"role": "user", "content": text}, **kw}


def say(text, m):
    return {"type": "assistant", "timestamp": T(m), "message": {"content": [{"type": "text", "text": text}]}}


def tool(name, m, uid="u"):
    return {"type": "assistant", "timestamp": T(m), "message": {"content": [{"type": "tool_use", "id": uid, "name": name, "input": {}}]}}


def result(m, text="ok", uid="u"):
    return {"type": "user", "timestamp": T(m), "message": {"content": [{"type": "tool_result", "tool_use_id": uid, "content": text}]}}


SESSION = [
    {"type": "custom-title", "customTitle": "my-session"},
    human("arreglá el botón", 0),
    say("Voy a mirar.", 1), tool("Bash", 1), result(1), tool("Agent", 2), result(2),
    say("Listo, el botón ya aparece en la home.", 3),
    {"type": "user", "timestamp": T(3), "message": {"content": [{"type": "text", "text": "<task-notification>\n<task-id>x</task-id>"}]}},
    human("<local-command-caveat>Caveat: ...</local-command-caveat>", 3, isMeta=True),
    human("This session is being continued from a previous conversation", 3, isCompactSummary=True),
    human("sigo sin ver el botón", 4),                          # turn 2; reaction to turn 1 = correction (visible)
    tool("Bash", 4), result(4, "The user doesn't want to proceed with this tool use. The tool use was rejected"),
    human("hacelo con css", 5),                                  # turn 3; turn 2 -> reject
    tool("Edit", 5), tool("Bash", 6, "u2"),
    {"type": "user", "timestamp": T(7), "message": {"content": [{"type": "text", "text": "[Request interrupted by user for tool use]"}]}},
    human("y el color?", 8),                                     # turn 4; turn 3 -> interrupt
    say("Rojo. ¿Querés que lo cambie?", 9),
    human("ok", 10),                                             # turn 5; turn 4 -> neutral
    say("Hecho.", 11),
]


class Classify(unittest.TestCase):
    def test_heuristic(self):
        h = ux.heuristic
        self.assertEqual(h("sigo sin ver el dashboard"), ("correction", "visible"))
        self.assertEqual(h("Sigue sin funcionar"), ("correction", "visible"))
        self.assertEqual(h("muy largo, más corto"), ("correction", "length"))
        self.assertEqual(h("no, eso no"), ("correction", None))
        self.assertEqual(h("por qué hiciste eso"), ("correction", None))
        self.assertEqual(h("explicá el paso 2"), ("more", None))
        self.assertEqual(h("y el color?"), ("more", None))
        self.assertEqual(h("dale, hacé el deploy"), ("neutral", None))
        self.assertEqual(h("formato normal"), ("neutral", None))  # "mal" only as a word
        self.assertEqual(h("está bien, pero en otro puerto"), ("correction", None))  # redirecting opener
        self.assertEqual(h("cuanto permite?"), ("more", None))  # short question, SHORT_Q_WORDS

    def test_d1_off_on_failure(self):
        d1 = ux.D1()
        ux.D1_URL, old = "http://127.0.0.1:9/ask", ux.D1_URL
        try:
            self.assertEqual(ux.classify("bien, seguí", "", d1), ("neutral", None))
            self.assertFalse(d1.on)
            self.assertEqual(d1.used, 0)
        finally:
            ux.D1_URL = old


class Turns(unittest.TestCase):
    def test_extract(self):
        turns, name = ux.parse(SESSION, "abcd1234")
        self.assertEqual(name, "my-session")
        self.assertEqual([c["next"] for c in turns], ["correction", "reject", "interrupt", "neutral", None])
        t1 = turns[0]
        self.assertEqual((t1["tool_calls"], t1["subagents"], t1["reply_words"], t1["min"]), (2, 1, 8, 3.0))
        self.assertEqual(t1["theme"], "visible")
        self.assertEqual(turns[2]["reply_words"], 0)  # no text after the last tool use
        self.assertTrue(turns[3]["asks"])
        self.assertEqual(turns[3]["user_text"], "y el color?")


class Contract(unittest.TestCase):
    def test_run(self):
        with tempfile.TemporaryDirectory() as d:
            proj = os.path.join(d, "root", "-home-u-app")
            os.makedirs(os.path.join(proj, "sid1", "subagents"))
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:")
            def fix(r):
                return dict(r, timestamp=now + r["timestamp"][14:]) if "timestamp" in r else r
            with open(os.path.join(proj, "sid1.jsonl"), "w") as f:
                f.writelines(json.dumps(fix(r)) + "\n" for r in SESSION)
            with open(os.path.join(proj, "sid1", "subagents", "agent-x.jsonl"), "w") as f:
                f.write(json.dumps(fix(human("subagent prompt", 0))) + "\n")
            ux.main(["--root", os.path.join(d, "root"), "--out", d, "--no-d1", "--days", "1"])
            with open(os.path.join(d, "orch_ux.json")) as f:
                r = json.load(f)
        self.assertEqual(set(r), {"generated", "window_days", "classifier", "overall", "calibration", "nudges", "sessions", "turns", "workers"})
        self.assertIsInstance(r["workers"]["n"], int)
        self.assertEqual(r["classifier"], "heuristic")
        self.assertEqual(set(r["overall"]), {"turns", "reply_words_p50", "reply_words_p90", "tools_per_turn_p50", "turn_min_p50", "turns_with_code", "code_words_p50",
                                             "interrupts", "rejections", "corrections", "more_requests"})
        self.assertEqual(r["overall"]["turns"], 5)
        self.assertEqual((r["overall"]["interrupts"], r["overall"]["rejections"], r["overall"]["corrections"]), (1, 1, 1))
        self.assertEqual(set(r["calibration"]), {"target_reply_words", "current_p50", "verdict", "why"})
        self.assertIn(r["calibration"]["verdict"], ("too_long", "ok", "too_short"))
        for n in r["nudges"]:
            self.assertEqual(set(n), {"id", "text", "evidence", "severity"})
            self.assertLessEqual(len(n["text"]), 140)
        self.assertEqual(r["sessions"][0]["sid"], "sid1")
        self.assertEqual(set(r["sessions"][0]), {"sid", "name", "turns", "reply_words_p50", "corrections", "interrupts",
                                                 "rejections", "more_requests", "last"})
        self.assertEqual(set(r["turns"][0]), {"ts", "sid", "user_words", "reply_words", "code_words", "tool_calls", "subagents", "min",
                                              "next", "user_text", "reply_text"})
        ro = ux.readout(r)
        self.assertEqual(ro["turns"], 5)

    def test_calibration(self):
        turns = [dict(reply_words=w, next="neutral", theme=None) for w in [50] * 30]
        c = ux.calibrate(turns)
        self.assertEqual(c["target_reply_words"], round((120 * 10 + 50 * 30) / 40))
        turns.append(dict(reply_words=200, next="correction", theme="length"))
        self.assertEqual(ux.calibrate(turns)["target_reply_words"], 68)  # min(68, 200 * 0.75)


NOTE = ("<task-notification>\n<task-id>w1</task-id>\n<tool-use-id>a1</tool-use-id>\n<status>completed</status>\n"
        "<result>Partly done: I stopped at the context limit. No commit yet.</result>\n"
        "<usage><subagent_tokens>70000</subagent_tokens></usage>\n</task-notification>")
WORKER = [human("hacé X con un worker", 0),
          {"type": "assistant", "timestamp": T(1), "message": {"content": [{"type": "tool_use", "id": "a1", "name": "Agent",
           "input": {"prompt": "Do X. Commit. Tests green. Stay under ~60k context.", "description": "do X"}}]}},
          result(1, "Async agent launched successfully", "a1"),
          {"type": "user", "timestamp": T(5), "message": {"content": [{"type": "text", "text": NOTE}]}},
          tool("Bash", 6, "b1"), result(6, "ok", "b1"), tool("Bash", 6, "b2"), result(6, "ok", "b2"),
          say("El worker quedó a medias.", 7)]


class Definitions(unittest.TestCase):
    """METHOD.md audit 2026-10-25: what counts as a human turn and as its reply."""
    def test_notification_reply_not_in_turn(self):
        lines = [human("hacé X", 0), tool("Bash", 1), result(1), say("Listo, X hecho.", 2),
                 {"type": "system", "subtype": "turn_duration", "timestamp": T(2)},
                 human("<task-notification><task-id>a</task-id></task-notification>", 3, origin={"kind": "task-notification"}),
                 say("El worker terminó con un reporte largo " * 5, 4), human("ok", 5)]
        turns, _ = ux.parse(lines, "s")
        self.assertEqual(len(turns), 2)
        self.assertEqual((turns[0]["reply_words"], turns[0]["min"]), (3, 2.0))

    def test_heartbeat_ends_response(self):
        lines = [human("hacé X", 0), say("Listo.", 1), human("Autonudge heartbeat (run until 18:50)", 2),
                 say("Sigo con lo pendiente, todo en orden.", 3), human("ok", 4)]
        turns, _ = ux.parse(lines, "s")
        self.assertEqual([c["reply_words"] for c in turns], [1, 0])

    def test_scripted_and_automated_not_human(self):
        self.assertIsNone(ux.human_text(human("say ok", 0, entrypoint="sdk-cli")))
        self.assertIsNone(ux.human_text(human("Another Claude session sent a message", 0, origin={"kind": "peer"})))
        self.assertEqual(ux.human_text(human("hola", 0, origin={"kind": "human"}, entrypoint="cli")), "hola")

    def test_paste_is_human_and_ignored_for_class(self):
        p = '<pasted_content id="1">\nthis is wrong, don\'t do it\n</pasted_content id="1">\n\n dale, seguí'
        self.assertIsNotNone(ux.human_text(human(p, 0, origin={"kind": "human"})))
        self.assertEqual(ux.heuristic(p), ("neutral", None))

    def test_resume_prompt_not_human(self):
        self.assertIsNone(ux.human_text(human("Resumed by another session: this session's process died", 0, origin={"kind": "human"})))

    def test_queued_prompts_one_turn(self):
        lines = [human("hacé X", 0), say("Listo.", 1), human("commit", 2), human("y seguí", 2), human("commit y seguí", 3),
                 tool("Bash", 4), result(4), say("Hecho, commit abc1234.", 5)]
        turns, _ = ux.parse(lines, "s")
        self.assertEqual([(c["user_words"], c["reply_words"]) for c in turns], [(2, 1), (6, 3)])

    def test_synthetic_reply_not_counted(self):
        syn = {"type": "assistant", "timestamp": T(1), "message": {"model": "<synthetic>", "content": [{"type": "text", "text": "No response requested."}]}}
        self.assertEqual(ux.parse([human("seguí", 0), syn], "s")[0][0]["reply_words"], 0)

    def test_what_happened_is_correction(self):
        self.assertEqual(ux.heuristic("queda tiempo, que paso")[0], "correction")
        self.assertEqual(ux.heuristic("what happened with the deploy?")[0], "correction")

    def test_code_words_apart(self):
        t = ux.parse([human("cuál es el flag?", 0), say("Usá esto:\n```\nfoo --bar baz\n```\nY listo.", 1)], "s")[0][0]
        self.assertEqual((t["reply_words"], t["code_words"]), (4, 3))


class Workers(unittest.TestCase):
    def test_worker(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "agent-w1.jsonl"), "w") as f:
                for c in (30000, 65000):
                    f.write(json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 1, "cache_read_input_tokens": c}}}) + "\n")
            ws = ux.workers_of(WORKER, "s1", d)
        self.assertEqual(len(ws), 1)
        w = ws[0]
        self.assertEqual((w["agent"], w["desc"], w["partial"], w["ctx_limit"], w["commit"], w["budget"], w["peak_ctx"]),
                         ("w1", "do X", True, True, False, 60000, 65001))
        self.assertTrue(w["over_budget"])
        self.assertEqual(w["gaps"], ["commit", "tests"])
        self.assertEqual(w["followup_calls"], 2)
        sm = ux.summarize_workers(ws * 3)
        self.assertEqual((sm["n"], sm["partial_rate"], sm["over_budget_rate"], sm["followup_calls_p50"]), (3, 1.0, 1.0, 2))
        self.assertIn("hit context limit", sm["examples"][0]["why"])
        ids = [n["id"] for n in ux.worker_nudges(ws * 3, sm)]
        self.assertEqual(ids, ["workers_partial", "workers_over_budget", "workers_report_gaps"])

    def test_grade(self):
        g = ux.grade("Done, commit 3f9a2b1. 41 passed.", "commit it, run tests, ≤60k context")
        self.assertEqual((g["commit"], g["tests"], g["partial"], g["budget"]), (True, True, False, 60000))


class Eval(unittest.TestCase):
    def test_heuristic_eval(self):
        rows = [json.loads(l) for l in open(os.path.join(os.path.dirname(ENTRY), ux.EVAL))]
        r = ux.evaluate(rows)
        self.assertEqual(r["total"]["n"], 52)
        self.assertEqual(r["total"]["heuristic"], 47)  # METHOD.md U-eval (52 rows, training)
        self.assertTrue(all(len(x["text"]) <= 120 for x in rows))

    def test_holdout_eval(self):
        d = os.path.dirname(ENTRY)
        rows = [json.loads(l) for l in open(os.path.join(d, ux.HOLDOUT))]
        seen = {json.loads(l)["text"] for l in open(os.path.join(d, ux.EVAL))}
        self.assertEqual(len(rows), 60)
        self.assertTrue(all(x["label"] in ux.NEXT_KINDS and x["text"] not in seen for x in rows))
        r = ux.evaluate(rows)  # no d1: heuristic only
        self.assertEqual((r["total"]["n"], r["total"]["heuristic"]), (60, 49))  # METHOD.md U-eval, holdout now training
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ux.main(["--holdout", "--no-d1"])
        self.assertEqual(json.loads(out.getvalue())["total"]["n"], 60)

    def test_test2_eval(self):
        d = os.path.dirname(ENTRY)
        rows = [json.loads(l) for l in open(os.path.join(d, ux.TEST2))]
        train = {json.loads(l)["text"] for f in (ux.EVAL, ux.HOLDOUT) for l in open(os.path.join(d, f))}
        self.assertEqual(len(rows), 39)
        self.assertTrue(all(x["label"] in ux.NEXT_KINDS and x["text"] not in train for x in rows))
        r = ux.evaluate(rows)  # no d1
        self.assertEqual((r["total"]["baseline"], r["total"]["heuristic"]), (21, 27))  # METHOD.md U-eval test2
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ux.main(["--test2", "--no-d1"])
        self.assertEqual(json.loads(out.getvalue())["total"]["n"], 39)


if __name__ == "__main__":
    unittest.main()
