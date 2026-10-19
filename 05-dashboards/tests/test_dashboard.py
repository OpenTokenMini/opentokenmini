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
                for bad in ("/data/../dashboard/serve.py", "/data/events/transcript.jsonl", "/data/otel/x.jsonl", "/data/"):
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
