import importlib.util, json, os, re, shutil, subprocess, threading, unittest, urllib.error, urllib.request

import pathlib  # numbered stage dirs aren't importable: find the repo
REPO = str(next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir()))
LIVE = os.path.join(REPO, "05-dashboards", "live")
PAGE = os.path.join(LIVE, "index.html")
SMOKE = os.path.join(REPO, "05-dashboards", "tests", "fixtures", "live", "smoke.js")
NODE = shutil.which("node")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class TestLivePage(unittest.TestCase):
    def test_no_external_resources(self):
        html = open(PAGE).read()
        for bad in ("http://", "https://", "<script src", "@import"):
            self.assertNotIn(bad, html)

    def test_api_calls_match_live_tools(self):
        """Every api("tool", {args}) in the page names a live.py tool and only its declared arguments."""
        lv = load("otm_live_t", os.path.join(REPO, "06-optional", "mcp-server", "live.py"))
        calls = re.findall(r'api\("(\w+)", \{([^}]*)\}', open(PAGE).read())
        self.assertEqual({t for t, _ in calls}, {"overview", "session", "node", "agents", "mcp_status", "orch_ux"})
        for tool, args in calls:
            if tool == "orch_ux":  # served file (serve.py ORCH_UX), not a live.py tool
                continue
            if tool in ("agents", "mcp_status") and tool not in lv.TOOL_ARGS:  # page falls back on 404
                continue
            for k in re.findall(r"(\w+):", args.replace("...(full ?", "")):
                if (tool, k) in (("agents", "all"), ("mcp_status", "verbose")) and k not in lv.TOOL_ARGS[tool]:  # page retries without it on 400
                    continue
                self.assertIn(k, lv.TOOL_ARGS[tool], f"{tool}: {k}")
        self.assertIn("full", lv.TOOL_ARGS["overview"])

    def test_served_page_has_live_view(self):
        serve = load("otm_live_serve_t", os.path.join(LIVE, "serve.py"))
        srv = serve.ThreadingHTTPServer(("127.0.0.1", 0), serve.H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            html = urllib.request.urlopen(f"http://127.0.0.1:{srv.server_port}/").read().decode()
            self.assertIn('id="live"', html)
            self.assertIn("LV_POLL_MS = 10000", html)
            self.assertIn("SLOW_FRAME_MS", html)
            fx = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{srv.server_port}/agents-fixture.json").read())
            self.assertEqual(set(fx), {"session", "totals", "agents"})
            self.assertIsNone(fx["agents"][0]["parent"])
            self.assertIn('fetch("console"', html)  # frontend errors go to serve.py LOG
        finally:
            srv.shutdown()

    def test_orch_ux_endpoint(self):
        """/api/orch_ux serves <data>/orch_ux.json as is, or 404 JSON {"error"} when the analyzer hasn't written it."""
        import tempfile
        serve = load("otm_live_serve_ux", os.path.join(LIVE, "serve.py"))
        tmp = pathlib.Path(tempfile.mkdtemp()) / "orch_ux.json"
        serve.ORCH_UX = tmp
        srv = serve.ThreadingHTTPServer(("127.0.0.1", 0), serve.H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{srv.server_port}/api/orch_ux"
        try:
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(url)
            self.assertEqual(e.exception.code, 404)
            self.assertIn("error", json.loads(e.exception.read()))
            tmp.write_text(open(os.path.join(LIVE, "orch-ux-fixture.json")).read())
            r = urllib.request.urlopen(url + "?")
            self.assertEqual(r.status, 200)
            self.assertEqual(json.loads(r.read()), json.loads(tmp.read_text()))
        finally:
            srv.shutdown()
            tmp.unlink(missing_ok=True)

    def test_dev_fixtures_follow_contracts(self):
        mcp = json.load(open(os.path.join(LIVE, "mcp-fixture.json")))
        self.assertTrue({"server", "window_h", "calls", "errors", "tools", "orchestrators", "recent"} <= set(mcp))
        ux = json.load(open(os.path.join(LIVE, "orch-ux-fixture.json")))
        self.assertTrue({"generated", "window_days", "overall", "calibration", "nudges", "sessions", "turns"} <= set(ux))
        ag = json.load(open(os.path.join(LIVE, "agents-fixture.json")))
        for a in ag["agents"]:  # optional worker fields: result str|null, wt null|{path, branch, ahead, dirty, merged}
            self.assertIsInstance(a.get("result"), (str, type(None)))
            if a.get("wt") is not None:
                self.assertEqual(set(a["wt"]), {"path", "branch", "ahead", "dirty", "merged"})
        self.assertIsInstance(ag["totals"].get("to_merge", 0), int)

    @unittest.skipUnless(NODE, "node not installed")
    def test_renders_and_drills_down(self):
        for mode in ("", "deeplink", "404"):
            with self.subTest(mode=mode or "normal"):
                r = subprocess.run([NODE, SMOKE, PAGE] + ([mode] if mode else []), capture_output=True, text=True, timeout=30)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("errors 0", r.stdout)


if __name__ == "__main__":
    unittest.main()
