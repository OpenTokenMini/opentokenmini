"""orch-nudge hook: silent on a calm session, fires on a 'sigo sin ver' prompt and on an interrupted long tool chain."""
import importlib.util, io, json, os, tempfile, time, unittest

HOOK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "orch-nudge.py")
_spec = importlib.util.spec_from_file_location("orch_nudge", HOOK)
hk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hk)


def T(m):
    return f"2026-10-02T10:{m:02d}:00Z"


def human(text, m):
    return {"type": "user", "timestamp": T(m), "message": {"content": text}}


def say(text, m):
    return {"type": "assistant", "timestamp": T(m), "message": {"content": [{"type": "text", "text": text}]}}


def tool(m, i):
    return {"type": "assistant", "timestamp": T(m), "message": {"content": [{"type": "tool_use", "id": f"u{i}", "name": "Bash", "input": {}}]}}


CALM = [human("hacé X", 0), say("Hecho.", 1), human("ahora Y", 2), say("Listo, Y funciona.", 3)]


class Hook(unittest.TestCase):
    def run_hook(self, lines, prompt, report=None):
        with tempfile.TemporaryDirectory() as d:
            tp = os.path.join(d, "s.jsonl")
            with open(tp, "w") as f:
                f.writelines(json.dumps(r) + "\n" for r in lines)
            rp = os.path.join(d, "orch_ux.json")
            if report:
                with open(rp, "w") as f:
                    json.dump(report, f)
            out = io.StringIO()
            t = time.time()
            self.assertEqual(hk.main(io.StringIO(json.dumps({"transcript_path": tp, "prompt": prompt})), out, rp), 0)
            self.assertLess(time.time() - t, 0.3)
            return out.getvalue().splitlines()

    def test_silent(self):
        report = {"nudges": [{"id": "long_replies", "text": "Shorter.", "evidence": "", "severity": "warn"}]}
        self.assertEqual(self.run_hook(CALM, "dale, seguí", report), [])

    def test_fires_on_visible_correction(self):
        report = {"nudges": [{"id": "ask_back", "text": "No questions.", "evidence": "", "severity": "warn"}]}
        out = self.run_hook(CALM, "sigo sin ver Y en la pantalla", report)
        self.assertEqual(len(out), 2)
        self.assertIn("check it yourself", out[0])
        self.assertEqual(out[1], "[orch-nudge] No questions.")

    def test_prompt_already_logged(self):
        out = self.run_hook(CALM + [human("sigue sin funcionar Y", 4)], "sigue sin funcionar Y")
        self.assertEqual(len(out), 1)

    def test_long_chain_interrupt(self):
        lines = [human("hacé Z", 0)] + [tool(1, i) for i in range(10)] + [
            {"type": "user", "timestamp": T(2), "message": {"content": [{"type": "text", "text": "[Request interrupted by user]"}]}}]
        out = self.run_hook(lines, "pará")
        self.assertTrue(any("10 tool calls" in l for l in out), out)

    def test_workers_partial(self):
        def usage(n):
            return {"input_tokens": 0, "cache_read_input_tokens": n, "cache_creation_input_tokens": 0}
        with tempfile.TemporaryDirectory() as d:
            tp = os.path.join(d, "s.jsonl")
            with open(tp, "w") as f:
                f.writelines(json.dumps(r) + "\n" for r in CALM)
            sub = os.path.join(d, "s", "subagents")
            os.makedirs(sub)
            agents = {  # name: (prompt, last assistant content, peak ctx)
                "over": ("Do X. Stay under ~50k context.", [{"type": "text", "text": "Done, abc1234."}], 80_000),
                "partial": ("Do Y.", [{"type": "text", "text": "Stopped before the tests: partial."}], 10_000),
                "running": ("Do Z.", [{"type": "tool_use", "id": "t", "name": "Bash", "input": {}}], 10_000),
                "ok": ("Do W. Stay under ~50k context.", [{"type": "text", "text": "Done."}], 20_000)}
            for name, (prompt, last, peak) in agents.items():
                with open(os.path.join(sub, f"agent-{name}.jsonl"), "w") as f:
                    f.write(json.dumps({"type": "user", "message": {"content": prompt}}) + "\n")
                    f.write(json.dumps({"type": "assistant", "message": {"content": last, "usage": usage(peak)}}) + "\n")
            old = os.path.join(sub, "agent-old.jsonl")
            with open(old, "w") as f:
                f.write(json.dumps({"type": "user", "message": {"content": "Do V."}}) + "\n")
                f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "incomplete"}]}}) + "\n")
            os.utime(old, (time.time() - 2 * hk.WORKER_WINDOW_S,) * 2)
            out = io.StringIO()
            hk.main(io.StringIO(json.dumps({"transcript_path": tp, "prompt": "dale"})), out, os.path.join(d, "none.json"))
            self.assertEqual(out.getvalue().splitlines(), ["[orch-nudge] " + hk.worker_rule(hk.load_analyzer(), tp)[0][1]])
            self.assertIn("1 partial and 1 over budget", out.getvalue())

    def test_bad_input_silent(self):
        out = io.StringIO()
        self.assertEqual(hk.main(io.StringIO("not json"), out), 0)
        self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
