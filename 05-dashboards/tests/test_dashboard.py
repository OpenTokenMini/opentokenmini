import importlib.util, json, os, shutil, subprocess, tempfile, threading, unittest, urllib.error, urllib.request

import pathlib  # numbered stage dirs aren't importable: find the repo, use 02-measure/ for imports
REPO = str(next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir()))
MEASURE = os.path.join(REPO, "02-measure")
FIX = os.path.join(MEASURE, "tests", "fixtures")  # readouts/ (shared contract fixtures)
PAGE = os.path.join(REPO, "05-dashboards", "standalone", "index.html")
SMOKE = os.path.join(REPO, "05-dashboards", "tests", "fixtures", "dashboard", "smoke.js")
NODE = shutil.which("node")


def load_serve():
    spec = importlib.util.spec_from_file_location("otm_dashboard_serve", os.path.join(REPO, "05-dashboards", "standalone", "serve.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class TestDashboard(unittest.TestCase):
    def test_no_external_resources(self):
        html = open(PAGE).read()
        for bad in ("http://", "https://", "<link ", " src="):
            self.assertNotIn(bad, html.replace('xmlns="http://www.w3.org/2000/svg"', ""))

    @unittest.skipUnless(NODE, "node not installed")
    def test_renders_fixture_and_empty_dir(self):
        with tempfile.TemporaryDirectory() as empty:
            for d in (os.path.join(FIX, "readouts"), empty):
                r = subprocess.run([NODE, SMOKE, PAGE, d], capture_output=True, text=True, timeout=30)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("errors 0", r.stdout)
        r = subprocess.run([NODE, SMOKE, PAGE, os.path.join(FIX, "readouts")], capture_output=True, text=True, timeout=30)
        self.assertIn("$0.017", r.stdout)  # analysis.json totals.cost.total 0.017375

    def smoke(self, d, card=None):
        r = subprocess.run([NODE, SMOKE, PAGE, d] + ([card] if card else []), capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("errors 0", r.stdout)
        return r.stdout

    @unittest.skipUnless(NODE, "node not installed")
    def test_delivery_card(self):
        rd = os.path.join(FIX, "readouts")
        out = self.smoke(rd, "impact")  # no delivery files: card and panels hidden, no red status
        self.assertNotIn("CI fail", out)
        self.assertNotIn("Pull requests", out)
        self.assertNotIn("deploys", out)
        with tempfile.TemporaryDirectory() as tmp:
            for sub in ("", "delivery"):
                for f in os.listdir(os.path.join(rd, sub)):
                    if f.endswith((".json", ".jsonl")):
                        shutil.copy(os.path.join(rd, sub, f), tmp)
            out = self.smoke(tmp, "impact")
            head = out.split("filtered head", 1)[1]
            self.assertIn("CI fail 50.0% vs 25.0% · PRs 3/4", head)
            self.assertIn("$/kept commit", head)
            for s in ("CI failure rate", "PRs linked 3/4", "ticketless 50.0%", "$ linked $2.50", "By ticket type"):
                self.assertIn(s, out)
        with tempfile.TemporaryDirectory() as tmp:  # readout only, no impact file, no ticket types; skipped issues stage
            shutil.copy(os.path.join(rd, "analysis.json"), tmp)
            with open(os.path.join(rd, "delivery", "readout.json")) as f:
                ro = json.load(f)
            ro["deployments"]["agent"] = {"failure_rate": 0.1, "n": 10}
            ro["deployments"]["baseline"] = {"failure_rate": 0.2, "n": 5}
            ro["issues"] = {"skipped": "gh not found"}
            with open(os.path.join(tmp, "readout.json"), "w") as f:
                json.dump(ro, f)
            out = self.smoke(tmp, "impact")
            self.assertIn("10.0% CI fail", out)
            self.assertNotIn("Pull requests", out)
            self.assertNotIn("PRs", out)
            self.assertIn("baseline 20.0% 5", out)
            for sec in ro:  # both stages skipped: card hidden
                if sec in ("deployments", "issues"):
                    ro[sec] = {"skipped": "network stages disabled"}
            with open(os.path.join(tmp, "readout.json"), "w") as f:
                json.dump(ro, f)
            out = self.smoke(tmp, "impact")
            self.assertNotIn("CI fail", out)
            self.assertNotIn("$/kept commit", out.split("filtered head", 1)[1])

    @unittest.skipUnless(NODE, "node not installed")
    def test_unknown_readout_sections_as_cards(self):
        rd = os.path.join(FIX, "readouts")
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(os.path.join(rd, "analysis.json"), tmp)
            ro = {"v": 1, "generated": "2026-01-01T00:00:00Z", "context": {"window_fill_rate": 0.42, "compactions": 3},
                  "orchestration": {"skipped": "no subagents"}, "mcp": {"never_called": ["a", "b"], "cost_wasted": 1.5}}
            with open(os.path.join(tmp, "readout.json"), "w") as f:
                json.dump(ro, f)
            out = self.smoke(tmp)
            self.assertIn("ago", out)  # data age in the header
            self.assertIn("sections 3", out)  # day chart + context + mcp; skipped orchestration hidden
            for s in ("window fill rate", "42.0%", "compactions", "never called", "$1.50"):
                self.assertIn(s, out)

    def test_serve_data_and_console_log(self):
        serve = load_serve()
        with tempfile.TemporaryDirectory() as tmp:
            serve.LOG = os.path.join(tmp, "console.jsonl")
            srv = serve.ThreadingHTTPServer(("127.0.0.1", 0), serve.handler(os.path.join(FIX, "readouts")))
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            base = f"http://127.0.0.1:{srv.server_address[1]}"
            try:
                r = urllib.request.urlopen(base + "/")
                self.assertEqual(r.headers["X-OTM-Dev"], "1")
                a = json.load(urllib.request.urlopen(base + "/data/analysis.json"))
                self.assertEqual(a["totals"]["calls"], 2)
                for bad in ("/data/../dashboard/serve.py", "/data/delivery/readout.json", "/data/deployments_summary.json", "/data/events/transcript.jsonl", "/data/otel/x.jsonl", "/data/"):
                    with self.assertRaises(urllib.error.HTTPError) as e:
                        urllib.request.urlopen(base + bad)
                    self.assertEqual(e.exception.code, 404, bad)
                req = urllib.request.Request(base + "/console", data=b'{"kind":"error","msg":"x"}', method="POST")
                self.assertEqual(urllib.request.urlopen(req).status, 204)
                with open(serve.LOG) as f:
                    self.assertEqual(json.loads(f.read())["kind"], "error")
            finally:
                srv.shutdown()
                srv.server_close()


if __name__ == "__main__":
    unittest.main()
