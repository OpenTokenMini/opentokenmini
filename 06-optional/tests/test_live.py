import importlib.util, io, json, os, tempfile, time, unittest

import pathlib  # numbered stage dirs aren't importable: find the repo, load live.py by path
REPO = str(next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir()))
spec = importlib.util.spec_from_file_location("otm_live", os.path.join(REPO, "06-optional", "mcp-server", "live.py"))
L = importlib.util.module_from_spec(spec); spec.loader.exec_module(L)

SID, AID = "11111111-aaaa-bbbb-cccc-000000000001", "a1b2c3d4"


def now_iso(off=0):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() + off))


def asst(mid, text=None, tool=None, out=500, ctx=40000):
    content = ([{"type": "text", "text": text}] if text else []) + ([{"type": "tool_use", "id": "tu" + mid, "name": tool[0], "input": tool[1]}] if tool else [])
    return {"type": "assistant", "timestamp": now_iso(-60), "message": {"id": mid, "model": "claude-opus-4-5", "content": content,
            "stop_reason": "end_turn" if text and not tool else "tool_use",
            "usage": {"input_tokens": 10, "cache_creation_input_tokens": 1000, "cache_read_input_tokens": ctx - 1010, "output_tokens": out}}}


class TestLive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); t = self.tmp.name
        self.data, self.repo = os.path.join(t, "data"), os.path.join(t, "repo")
        os.makedirs(os.path.join(self.repo, ".git")); os.makedirs(os.path.join(self.repo, "src", "pkg"))
        self.edited = os.path.join(self.repo, "src", "pkg", "a.py")
        proj = os.path.join(t, "projects", "p1"); subs = os.path.join(proj, SID, "subagents"); os.makedirs(subs)
        sess = os.path.join(t, "sessions"); os.makedirs(sess)
        json.dump({"sessionId": SID, "pid": os.getpid(), "status": "busy", "name": "alpha", "cwd": self.repo}, open(os.path.join(sess, "1.json"), "w"))
        main = [{"type": "user", "timestamp": now_iso(-120), "cwd": self.repo, "message": {"content": "Build the widget please"}},
                asst("m1", tool=("Edit", {"file_path": self.edited})),
                asst("m2", tool=("Bash", {"command": "python3 -m http.server 7845"})),
                {"type": "user", "timestamp": now_iso(-30), "toolUseResult": {"agentId": AID, "status": "completed", "description": "Scout things",
                 "content": [{"type": "text", "text": "short"}], "totalDurationMs": 180000}, "message": {"content": [{"type": "tool_result", "content": "x"}]}},
                asst("m3", text="Done.")]
        with open(os.path.join(proj, SID + ".jsonl"), "w") as h:
            h.writelines(json.dumps(x, separators=(",", ":")) + "\n" for x in main)  # compact like Claude Code: scan() prefilters on it
        sub = [{"type": "user", "timestamp": now_iso(-200), "isSidechain": True, "message": {"content": "scout"}},
               asst("s1", tool=("Grep", {"pattern": "x", "path": self.repo}), out=50000, ctx=60000), asst("s2", text="short")]
        with open(os.path.join(subs, f"agent-{AID}.jsonl"), "w") as h:
            h.writelines(json.dumps(x, separators=(",", ":")) + "\n" for x in sub)
        json.dump({"agentType": "Explore", "description": "Scout things", "model": "haiku"}, open(os.path.join(subs, f"agent-{AID}.meta.json"), "w"))
        self.quota = os.path.join(t, "quota.json")
        json.dump({"ts": time.time(), "out": [[19.0, "5h  [#]  19%  resets Sun 09:49  (4k)"], [21.0, "7d  [#]  21%  resets Sun 18:59"]]}, open(self.quota, "w"))
        self.saved = {k: getattr(L, k) for k in ("SESSIONS_DIR", "PROJECTS_DIR", "QUOTA_CACHE")}
        L.SESSIONS_DIR, L.PROJECTS_DIR, L.QUOTA_CACHE = sess, os.path.join(t, "projects"), self.quota
        self.env = {k: os.environ.get(k) for k in ("OTM_DATA_DIR", "OTM_CONFIG", "CLAUDE_CODE_SESSION_ID")}
        os.environ["OTM_DATA_DIR"] = self.data
        os.environ.pop("OTM_CONFIG", None); os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
        L._SCANS.clear(); L._ROOTS.clear(); L._WT.clear(); L._OUTCOME.clear()
        self.d1 = L._D1[0]; L._D1[0] = False  # no network in tests unless a test stubs d1

    def tearDown(self):
        L._D1[0] = self.d1
        for k, v in self.saved.items():
            setattr(L, k, v)
        for k, v in self.env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.tmp.cleanup()

    def call(self, name, args):
        err, data = L.call_tool(name, args)
        self.assertFalse(err, data)
        return data

    def test_quota_reset_and_stale_fixed_clock(self):
        from datetime import datetime
        T = lambda *a: datetime(*a).timestamp()  # local time, like bgjobs' '%a %H:%M'
        ts = T(2026, 10, 25, 14, 38)  # Sunday; the dogfooding case: 5h resets 14:49, read at 14:58
        json.dump({"ts": ts, "out": [[89.0, "5h  [#]  89%  resets Sun 14:49  (17k of ~19k tokens)"], [35.0, "7d  [#]  35%  resets Sun 18:59"]]}, open(self.quota, "w"))
        q = L.quota(now=T(2026, 10, 25, 14, 58))
        self.assertEqual(q, {"5h": {"pct": None, "resets": "Sun 14:49", "reset": True}, "7d": {"pct": 35.0, "resets": "Sun 18:59"}, "age_min": 20, "stale": True})
        self.assertEqual(L.quota(now=T(2026, 10, 25, 14, 49, 30))["5h"]["pct"], 89.0)  # still inside the shown minute
        self.assertNotIn("stale", L.quota(now=ts + 60))
        # 7d: same weekday earlier in the day -> next week, not passed; day rollover Sat -> Sun
        self.assertFalse(L._reset_passed("Sun 09:00", ts, T(2026, 10, 31, 23, 0)))
        self.assertTrue(L._reset_passed("Sun 09:00", ts, T(2026, 11, 1, 9, 1)))
        self.assertFalse(L._reset_passed("Sun 01:10", T(2026, 10, 24, 22, 0), T(2026, 10, 25, 1, 0)))
        self.assertTrue(L._reset_passed("Sun 01:10", T(2026, 10, 24, 22, 0), T(2026, 10, 25, 1, 11)))
        self.assertFalse(L._reset_passed("?", ts, ts + 1e6))

    def test_overview_subagents_quota_and_delta(self):
        o = self.call("overview", {"caller": "me"})
        self.assertIsNone(o["delta"])
        s = o["measured"]["sessions"][0]
        self.assertEqual((s["name"], s["state"], s["goal"], s["ctx_k"]), ("alpha", "working", "Build the widget please", 40))
        self.assertEqual(s["touching"], [os.path.basename(os.path.dirname(self.repo)) + "/repo/src/pkg/"])
        self.assertEqual(len(s["subagents"]), 1)
        desc, model, ctx, cost, mins, tool, status = s["subagents"][0].split(" | ")
        self.assertEqual((desc, model, ctx, mins, tool, status), ("Scout things", "opus-4-5", "ctx 40k", "3m", "Grep", "completed"))
        self.assertTrue(cost.startswith("$") and float(cost[1:]) > 0)
        self.assertEqual(o["quota"]["7d"]["pct"], 21.0)
        self.assertEqual([i["issue"] for i in o["inferred"]], ["low_return"])
        o2 = self.call("overview", {"caller": "me"})
        self.assertEqual((o2["delta"], o2["measured"]["sessions"], o2["measured"]["unchanged"]), ([], [], 1))
        self.assertIsNotNone(o2["since"])

    def test_overview_drops_live_idle_session_older_than_window(self):  # real: live but idle "otm-dashboards", last activity 4 days ago
        t, old = self.tmp.name, "22222222-aaaa-bbbb-cccc-000000000002"
        p = os.path.join(t, "projects", "p1", old + ".jsonl")
        with open(p, "w") as h:
            h.write(json.dumps({"type": "user", "timestamp": now_iso(-4 * 86400), "message": {"content": "old"}}) + "\n")
        os.utime(p, (time.time() - 4 * 86400,) * 2)
        json.dump({"sessionId": old, "pid": os.getpid(), "status": "idle", "name": "stale", "statusUpdatedAt": (time.time() - 4 * 86400) * 1000},
                  open(os.path.join(t, "sessions", "2.json"), "w"))
        names = [s["name"] for s in self.call("overview", {"full": True})["measured"]["sessions"]]
        self.assertEqual(names, ["alpha"])
        self.assertIn("stale", [s["name"] for s in L.all_sessions(L.LOOKUP_WINDOW_H)])  # session/node lookups still find it

    def test_touching_ignores_finished_subagents(self):  # real: otm-orque listed dirs of workers merged hours earlier
        sub_dir = os.path.join(self.repo, "lib", "done")
        os.makedirs(sub_dir)
        f = os.path.join(self.tmp.name, "projects", "p1", SID, "subagents", f"agent-{AID}.jsonl")
        sub = [{"type": "user", "timestamp": now_iso(-200), "isSidechain": True, "message": {"content": "scout"}},
               asst("s1", tool=("Edit", {"file_path": os.path.join(sub_dir, "b.py")})), asst("s2", text="short")]
        with open(f, "w") as h:
            h.writelines(json.dumps(x, separators=(",", ":")) + "\n" for x in sub)
        s = self.call("overview", {"full": True})["measured"]["sessions"][0]
        self.assertEqual(s["touching"], [os.path.basename(os.path.dirname(self.repo)) + "/repo/src/pkg/"])
        self.assertIn(os.path.join(sub_dir, "b.py"), L.all_sessions(6)[0]["edited"])  # overlaps still see it
        with open(f, "w") as h:  # same worker still running (last event a tool call, written just now)
            h.writelines(json.dumps(x, separators=(",", ":")) + "\n" for x in sub[:2])
        L._SCANS.clear()
        s = self.call("overview", {"full": True})["measured"]["sessions"][0]
        self.assertIn(os.path.basename(os.path.dirname(self.repo)) + "/repo/lib/done/", s["touching"])

    def test_low_return_exempts_commit(self):  # real: workers that committed code flagged for returning ~1k chars
        self.assertEqual([i["issue"] for i in self.call("overview", {"full": True})["inferred"]], ["low_return"])
        p = os.path.join(self.tmp.name, "projects", "p1", SID + ".jsonl")
        with open(p) as h:
            s = h.read().replace('"text":"short"', '"text":"Commit c394e8c on wt/x. No merge."')
        with open(p, "w") as h:
            h.write(s)
        L._SCANS.clear()
        self.assertEqual(self.call("overview", {"full": True})["inferred"], [])

    def test_record_ledger(self):
        self.assertEqual(self.call("overview", {"full": True})["ledger"], [])
        st = self.call("record", {"phase": "start", "item": "issue-7", "agent": "otm-worker", "topology": "single"})
        self.assertEqual(st["quota_before"], {"5h": 19.0, "7d": 21.0})
        json.dump({"ts": time.time(), "out": [[25.0, "5h  [#]  25%"], [23.0, "7d  [#]  23%"]]}, open(self.quota, "w"))
        line = self.call("record", {"phase": "end", "item": "issue-7", "tokens": 120000, "commit": "abc123", "tests_pass": True, "accepted": True})
        self.assertEqual((line["agent"], line["topology"], line["quota_before"]["7d"], line["quota_after"]["7d"]), ("otm-worker", "single", 21.0, 23.0))
        rows = [json.loads(l) for l in open(os.path.join(self.data, "delegations.jsonl"))]
        self.assertEqual(len(rows), 1)
        self.assertEqual(set(rows[0]), {"ts", "agent", "desc", "item", "topology", "quota_before", "quota_after", "tokens", "commit", "tests_pass", "accepted"})
        tail = self.call("overview", {"full": True})["ledger"]
        self.assertEqual(len(tail), 1); self.assertIn("issue-7 otm-worker single 7d 21.0->23.0 tok 120000", tail[0])
        with self.assertRaises(L.ArgError):
            L.call_tool("record", {"phase": "middle", "item": "x"})

    def test_session_and_nodes(self):
        s = self.call("session", {"id_or_name": "alpha"})
        self.assertEqual((s["goal"]["src"], s["measured"]["turns_total"], s["measured"]["nodes_total"]), ("inferred", 1, 1))
        self.assertEqual(s["measured"]["files"][0], {"path": "src/pkg/a.py", "kind": "edit", "last": s["measured"]["files"][0]["last"]})
        t1 = self.call("node", {"session": SID[:8], "node": "t1"})
        self.assertEqual((t1["kind"], t1["tools"], t1["excerpt"]), ("turn", {"Edit": 1, "Bash": 1}, "Done."))
        n = self.call("node", {"session": "alpha", "node": AID[:4]})
        self.assertEqual((n["kind"], n["type"], n["status"], n["returned"], n["excerpt"]), ("subagent", "Explore", "completed", 5, "short"))
        self.assertTrue(L.call_tool("node", {"session": "alpha", "node": "t9"})[0])

    def test_agents_tree(self):
        subs = os.path.join(self.tmp.name, "projects", "p1", SID, "subagents")
        nested = [{"type": "user", "timestamp": now_iso(-100), "isSidechain": True, "message": {"content": "dig deeper\nsecond line"}},
                  asst("n1", tool=("Read", {"file_path": self.edited}), ctx=90000), asst("n2", tool=("Bash", {"command": "ls"}), ctx=20000)]
        with open(os.path.join(subs, "agent-ffff0000eeee.jsonl"), "w") as h:
            h.writelines(json.dumps(x, separators=(",", ":")) + "\n" for x in nested)
        json.dump({"agentType": "general-purpose", "parentAgentId": AID, "spawnDepth": 2}, open(os.path.join(subs, "agent-ffff0000eeee.meta.json"), "w"))
        d = self.call("agents", {"session": "alpha"})
        self.assertEqual(set(d), {"session", "totals", "agents", "omitted"})
        self.assertEqual(d["omitted"], 0)
        self.assertEqual(d["session"], {"name": "alpha", "sid": SID[:8], "state": "working"})
        m, w1, w2 = d["agents"]
        self.assertEqual(set(m), {"id", "parent", "desc", "model", "state", "cost", "ctx_k", "peak_ctx_k", "turns", "tool_calls", "started", "last", "duration_s"})
        self.assertEqual((m["id"], m["parent"], m["desc"], m["model"], m["state"], m["turns"], m["tool_calls"]),
                         (SID[:8], None, "Build the widget please", "opus-4-5", "working", 3, 2))
        self.assertEqual((w1["id"], w1["parent"], w1["desc"], w1["state"], w1["ctx_k"], w1["turns"]), (AID, SID[:8], "Scout things", "done", 40, 2))
        self.assertEqual((w2["id"], w2["parent"], w2["desc"], w2["state"], w2["ctx_k"], w2["peak_ctx_k"]), ("ffff0000", AID, "dig deeper", "working", 20, 90))
        t = d["totals"]
        self.assertEqual((t["workers"], t["running"], t["median_ctx_k"]), (2, 1, 30))
        self.assertAlmostEqual(t["cost"], t["orch_cost"] + t["workers_cost"], places=1)
        self.assertGreater(t["workers_cost"], t["orch_cost"])
        os.environ["CLAUDE_CODE_SESSION_ID"] = SID  # default: the caller's session; limit keeps the newest workers
        d = self.call("agents", {"limit": 1})
        self.assertEqual(([a["id"] for a in d["agents"]], d["over_limit"]), ([SID[:8], "ffff0000"], 1))

    def test_agents_since_heartbeat(self):
        subs = os.path.join(self.tmp.name, "projects", "p1", SID, "subagents")
        with open(os.path.join(subs, "agent-ffff0000eeee.jsonl"), "w") as h:
            h.write(json.dumps({"type": "user", "timestamp": now_iso(-100), "isSidechain": True, "message": {"content": "dig"}}) + "\n")
            h.write(json.dumps(asst("n1", tool=("Bash", {"command": "ls"}))) + "\n")
        d = self.call("agents", {"session": "alpha", "since": ""})  # first beat: running + actionable only
        self.assertEqual(set(d), {"cursor", "basis", "summary", "changed", "unchanged"})
        self.assertEqual((d["basis"], [w["id"] for w in d["changed"]], d["unchanged"]), ("actionable", ["ffff0000"], 1))
        self.assertEqual(d["summary"], "1 running, quota 5h 19% 7d 21%")
        c = d["cursor"]
        d = self.call("agents", {"session": "alpha", "since": c})
        self.assertEqual((d["basis"], d["changed"], d["unchanged"]), ("cursor", [], 2))
        store = L._load("agents_cursors.json")  # pretend the last beat saw ffff0000 finished
        store[SID][d["cursor"]]["ffff0000"] = ["done", "ok", None]
        L._save("agents_cursors.json", store)
        d = self.call("agents", {"session": "alpha", "since": d["cursor"]})
        self.assertEqual([(w["id"], w["state"], w["was"]) for w in d["changed"]], [("ffff0000", "working", "done")])
        d = self.call("agents", {"session": "alpha", "since": now_iso(-3600)})  # ISO older than any snapshot: activity since then
        self.assertEqual((d["basis"], len(d["changed"])), ("activity", 2))
        self.assertEqual(L.quota_line({"5h": {"pct": None, "resets": "x", "reset": True}, "age_min": 20, "stale": True}), "quota 5h reset stale 20m")
        self.assertEqual(L.quota_line(None), "quota ?")
        self.assertIn("omitted", self.call("agents", {"session": "alpha"}))  # default view unchanged

    def test_agents_and_session_share_workers(self):
        subs = os.path.join(self.tmp.name, "projects", "p1", SID, "subagents")
        for i in range(25):  # more than AGENTS_ROWS and SESSION_NODES: all=true must still list every worker
            rows = [{"type": "user", "timestamp": now_iso(-900 + i), "isSidechain": True, "message": {"content": f"job {i}"}}, asst(f"j{i}", text="ok")]
            with open(os.path.join(subs, f"agent-beef{i:04d}.jsonl"), "w") as h:
                h.writelines(json.dumps(x, separators=(",", ":")) + "\n" for x in rows)
        A = {w["id"]: w for w in self.call("agents", {"session": "alpha", "all": True})["agents"][1:]}
        N = {n["node"]: n for n in self.call("session", {"id_or_name": "alpha", "limit": 100})["measured"]["nodes"]}
        self.assertEqual(set(A), set(N))
        self.assertEqual(len(A), 26)
        for k, w in A.items():
            self.assertEqual((w["state"], w["outcome"], w["duration_s"], w["last"]), (N[k]["state"], N[k]["outcome"], N[k]["dur_s"], N[k]["last"]), k)
        self.assertEqual(A[AID]["duration_s"], 180)  # parent-measured totalDurationMs wins in both
        dflt = self.call("session", {"id_or_name": "alpha"})["measured"]["nodes"]
        self.assertTrue({n["node"] for n in dflt} <= set(A))

    def test_timestamps_utc(self):
        self.assertEqual(L._iso("2026-10-25T10:05:30-03:00"), "2026-10-25T13:05Z")
        self.assertEqual(L._iso("2026-10-25T13:05:30.123Z"), "2026-10-25T13:05Z")
        self.assertEqual(L._iso("2026-10-25T13:05:30"), "2026-10-25T13:05Z")  # naive = UTC
        self.assertEqual(L._iso(1792933500), "2026-10-25T13:05Z")
        subs = os.path.join(self.tmp.name, "projects", "p1", SID, "subagents")
        t0 = time.time() - 400
        loc = lambda t: time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t - 3 * 3600)) + "-03:00"  # same instant, local offset
        rows = [{"type": "user", "timestamp": loc(t0), "isSidechain": True, "message": {"content": "tz"}}, asst("z1", text="done")]
        rows[1]["timestamp"] = loc(t0 + 60)
        with open(os.path.join(subs, "agent-cafe0001.jsonl"), "w") as h:
            h.writelines(json.dumps(x, separators=(",", ":")) + "\n" for x in rows)
        d = self.call("agents", {"session": "alpha", "all": True})
        w = next(x for x in d["agents"] if x["id"] == "cafe0001")
        utc = lambda t: time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(t))
        self.assertEqual((w["started"], w["last"], w["duration_s"]), (utc(t0), utc(t0 + 60), 60))
        for x in d["agents"]:
            for k in ("started", "last"):
                self.assertRegex(x[k], r"^\d{4}-\d\d-\d\dT\d\d:\d\dZ$")

    def test_agents_default_trims_finished(self):
        subs = os.path.join(self.tmp.name, "projects", "p1", SID, "subagents")
        for i in range(7):  # 7 more finished workers (plus AID finished): default keeps the 5 newest finished
            with open(os.path.join(subs, f"agent-dddd000{i}.jsonl"), "w") as h:
                h.writelines(json.dumps(x, separators=(",", ":")) + "\n" for x in
                             [{"type": "user", "timestamp": now_iso(-3000 + i * 100), "isSidechain": True, "message": {"content": f"job {i}"}},
                              {**asst(f"d{i}", text="ok"), "timestamp": now_iso(-2900 + i * 100)}])
            os.utime(h.name, (time.time() - 2900 + i * 100,) * 2)  # last = mtime; AID (written now) is the newest finished
        with open(os.path.join(subs, "agent-eeee0000.jsonl"), "w") as h:  # running: tool_use pending, just written
            h.writelines(json.dumps(x, separators=(",", ":")) + "\n" for x in
                         [{"type": "user", "timestamp": now_iso(-5000), "isSidechain": True, "message": {"content": "long job"}},
                          asst("e1", tool=("Bash", {"command": "ls"}))])
        full = self.call("agents", {"session": "alpha", "all": True})
        self.assertEqual((len(full["agents"]), full["omitted"], full["totals"]["workers"]), (10, 0, 9))
        d = self.call("agents", {"session": "alpha"})
        self.assertEqual((d["session"], d["totals"]), (full["session"], full["totals"]))
        ids = [a["id"] for a in d["agents"]]
        self.assertEqual((ids[0], d["omitted"], len(ids)), (SID[:8], 3, 7))
        self.assertIn("eeee0000", ids); self.assertIn(AID, ids)
        self.assertEqual(sorted(i for i in ids if i.startswith("dddd")), [f"dddd000{i}" for i in range(3, 7)])

    def _log(self):
        with open(os.path.join(self.data, "live", "calls.jsonl")) as h:
            return [json.loads(l) for l in h]

    def test_agents_result_and_worktrees(self):
        import subprocess
        g = lambda d, *a: subprocess.run(["git", "-C", d, *a], check=True, capture_output=True, text=True).stdout
        repo, t = os.path.join(self.tmp.name, "gitrepo"), self.tmp.name
        os.makedirs(repo); g(repo, "init", "-q", "-b", "main")
        g(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "base")
        wts = {n: os.path.join(t, f"wt-{n}") for n in ("tomerge", "dirty", "merged")}
        for n, w in wts.items():
            g(repo, "worktree", "add", "-q", "-b", f"wt/{n}", w)
        for n in ("tomerge", "merged"):
            g(wts[n], "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", n)
        g(repo, "-c", "user.email=t@t", "-c", "user.name=t", "merge", "-q", "--no-ff", "-m", "m", "wt/merged")
        open(os.path.join(wts["dirty"], "x.txt"), "w").write("x")
        subs = os.path.join(t, "projects", "p1", SID, "subagents")
        for i, n in enumerate(("tomerge", "dirty", "merged")):
            prompt = f"You work in the git worktree {wts[n]} (branch wt/{n}). See https://claude.ai/code/x, /api/ then edit {wts[n]}/a.py and /etc/hosts."
            rows = [{"type": "user", "timestamp": now_iso(-300 + i), "isSidechain": True, "message": {"content": prompt}},
                    asst(f"w{i}", text=f"Report  {n}:\n  commit  abc " + "y" * 300)]
            with open(os.path.join(subs, f"agent-cafe000{i}.jsonl"), "w") as h:
                h.writelines(json.dumps(x, separators=(",", ":")) + "\n" for x in rows)
            os.utime(os.path.join(subs, f"agent-cafe000{i}.jsonl"), (time.time() - 400, time.time() - 400))
        d = self.call("agents", {"session": "alpha", "all": True})
        m, ws = d["agents"][0], {w["id"]: w for w in d["agents"][1:]}
        self.assertNotIn("wt", m); self.assertNotIn("result", m)
        self.assertEqual(ws[AID]["result"], "short")  # result the parent received
        self.assertIsNone(ws[AID]["wt"])
        r = ws["cafe0000"]["result"]
        self.assertTrue(r.startswith("Report tomerge: commit abc yyy")); self.assertEqual(len(r), L.AGENT_RESULT_CHARS)
        self.assertEqual(ws["cafe0000"]["wt"], {"path": wts["tomerge"], "branch": "wt/tomerge", "ahead": 1, "dirty": 0, "merged": False})
        self.assertEqual(ws["cafe0001"]["wt"], {"path": wts["dirty"], "branch": "wt/dirty", "ahead": 0, "dirty": 1, "merged": False})
        self.assertEqual(ws["cafe0002"]["wt"], {"path": wts["merged"], "branch": "wt/merged", "ahead": 0, "dirty": 0, "merged": True})
        self.assertEqual(d["totals"]["to_merge"], 1)
        g(wts["dirty"], "add", "x.txt")  # git facts are cached for WT_CACHE_S
        self.assertEqual(next(w for w in self.call("agents", {"session": "alpha", "all": True})["agents"] if w["id"] == "cafe0001")["wt"]["dirty"], 1)
        os.rename(wts["tomerge"], wts["tomerge"] + "-gone")  # removed worktree -> null at once (fs check precedes the cache)
        d = self.call("agents", {"session": "alpha", "all": True})
        self.assertIsNone(next(w for w in d["agents"] if w["id"] == "cafe0000")["wt"])
        self.assertEqual(d["totals"]["to_merge"], 0)

    def test_agents_merged_worker_without_worktree(self):
        import subprocess
        g = lambda d, *a: subprocess.run(["git", "-C", d, *a], check=True, capture_output=True, text=True).stdout
        repo = os.path.join(self.tmp.name, "gitrepo2")
        os.makedirs(repo); g(repo, "init", "-q", "-b", "main")
        g(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "base")
        sha = g(repo, "rev-parse", "--short", "HEAD").strip()  # worker's commit, already in main; its worktree dir was removed
        gone = os.path.join(repo, ".claude", "worktrees", "agent-gone")
        final = f"Listo en wt/mcp14, commit {sha}. No mergeé ni pusheé nada. " + "palabra " * 40
        rows = [{"type": "user", "timestamp": now_iso(-300), "isSidechain": True, "message": {"content": f"Work in {gone}, then commit."}},
                asst("g0", text=final)]
        subs = os.path.join(self.tmp.name, "projects", "p1", SID, "subagents")
        with open(os.path.join(subs, "agent-beef0000.jsonl"), "w") as h:
            h.writelines(json.dumps(x, separators=(",", ":")) + "\n" for x in rows)
        os.utime(os.path.join(subs, "agent-beef0000.jsonl"), (time.time() - 400, time.time() - 400))
        w = next(w for w in self.call("agents", {"session": "alpha", "all": True})["agents"] if w["id"] == "beef0000")
        self.assertEqual(w["wt"], {"path": None, "branch": "wt/mcp14", "ahead": 0, "dirty": 0, "merged": True})
        self.assertTrue(w["result"].endswith(" palabra…"), w["result"])  # cut at a word boundary
        self.assertLessEqual(len(w["result"]), L.AGENT_RESULT_CHARS)
        self.assertEqual(L._cut("uno dos tres", 9), "uno dos…")

    def test_agents_outcome_duration_markdown(self):
        subs = os.path.join(self.tmp.name, "projects", "p1", SID, "subagents")
        finals = {"ok": "I committed **4556f8a** on wt/x. All tests pass.",
                  "partial": "I hit the context hard limit before committing, so there is no commit hash.",
                  "failed": "Could not start: the server returned an error on every call.",
                  "nocommit": "The code works now.",  # no keyword -> d1 (stub: partial)
                  "ambig": "Fixed the failed test and committed 1c5a3a7.",  # commit hash outweighs fail words
                  "guard": "The work isn't finished. Nothing is committed.",
                  "both": "Tests pass but the build failed."}  # ok + fail words -> d1
        for i, (n, text) in enumerate(finals.items()):
            a = asst(f"o{i}", text=text); a["timestamp"] = now_iso(-500)
            rows = [{"type": "user", "timestamp": now_iso(-600), "isSidechain": True, "message": {"content": f"Do {n}, then commit."}}, a,
                    {"type": "user", "timestamp": now_iso(-5), "isSidechain": True,  # task notification appended much later
                     "message": {"content": "[SYSTEM NOTIFICATION - NOT USER INPUT] background task finished"}}]
            with open(os.path.join(subs, f"agent-face000{i}.jsonl"), "w") as h:
                h.writelines(json.dumps(x, separators=(",", ":")) + "\n" for x in rows)
        L._D1[0] = True
        seen = []
        def fake_urlopen(req, timeout):
            seen.append(json.loads(req.data)); self.assertEqual(timeout, L.D1_TIMEOUT_S)
            return io.BytesIO(json.dumps({"answer": {"choice": "partial" if "works now" in seen[-1]["state"] else "ok", "confidence": 0.9}}).encode())
        saved, L.urllib.request.urlopen = L.urllib.request.urlopen, fake_urlopen
        try:
            d = self.call("agents", {"session": "alpha", "all": True})
            self.call("agents", {"session": "alpha", "all": True})  # cached per agent id + text: d1 asked once each (nocommit, ambig, fixture "short")
        finally:
            L.urllib.request.urlopen = saved
        ws = {w["id"]: w for w in d["agents"][1:]}
        self.assertEqual([ws[f"face000{i}"]["outcome"] for i in range(7)], ["ok", "partial", "failed", "partial", "ok", "partial", "ok"])
        self.assertEqual(len(seen), 3); self.assertEqual([o[0] for o in seen[0]["opts"]], ["ok", "partial", "failed"])
        self.assertEqual(d["totals"]["partial"], 3)
        w = ws["face0000"]
        self.assertEqual((w["state"], w["duration_s"]), ("done", 100))  # last work event, not the notification
        self.assertEqual(w["last"], L._iso(now_iso(-500)))
        self.assertEqual(w["result"], "I committed 4556f8a on wt/x. All tests pass.")
        self.assertEqual(w["turns"], 1)
        L._OUTCOME.clear()  # d1 down -> disabled for the process, keyword fallback
        def down(req, timeout):
            raise OSError("refused")
        L.urllib.request.urlopen = down
        try:
            self.assertEqual(L._d1_outcome("g", "t"), None); self.assertFalse(L._D1[0])
        finally:
            L.urllib.request.urlopen = saved

    def test_agents_handoff_and_next(self):
        hd = os.path.join(self.tmp.name, "handoffs"); os.makedirs(hd)
        named, own = os.path.join(hd, "otm-x.md"), os.path.join(hd, "aaa1.md")
        open(named, "w").write("h"); open(own, "w").write("h")
        saved, L.HANDOFF_DIR = L.HANDOFF_DIR, hd
        try:
            x = lambda t: {"turns": [{"text": t}]}
            self.assertEqual(L.handoff("zzz", x(f"Stopped. Next steps in `{named}`."), {}), named)
            self.assertEqual(L.handoff("aaa1", x("Stopped, see /nope/handoffs/gone.md"), {}), own)  # missing file skipped, own id used
            self.assertIsNone(L.handoff("zzz", x("done"), {}))
        finally:
            L.HANDOFF_DIR = saved
        wt = lambda ahead=0, dirty=0, merged=False, path="/w": {"path": path, "ahead": ahead, "dirty": dirty, "merged": merged}
        row = lambda o, w=None, h=None, st="done": {"state": st, "outcome": o, "wt": w, **({"handoff": h} if h else {})}
        none = (set(), set())
        cases = [(row("ok", wt(1)), none, "merge"), (row("ok", wt(1, dirty=2)), none, "inspect"), (row("partial", wt(1)), none, "inspect"),
                 (row("partial", None, named), none, "resume"), (row("partial"), none, "inspect"), (row("failed"), none, "inspect"),
                 (row("ok", wt()), none, None), (row("partial", wt(merged=True), named), none, None), (row(None, wt(1), st="working"), none, None),
                 (row("partial", wt(), named), ({named}, set()), None), (row("failed", wt()), (set(), {"/w"}), None)]  # resumed/redone later
        for r, later, want in cases:
            self.assertEqual(L.next_step(r, later), want, r)

    def test_stale_action(self):  # real: otm-orque kept "1 to inspect" for a partial worker finished 5h earlier, long after the user moved on
        now = 1_800_000_000
        iso = lambda h: L._iso(now - h * 3600)
        w = lambda n="inspect", h=5: {"next": n, "last": iso(h)}
        merged = [{"wt": {"merged": True}}]
        self.assertTrue(L.stale_action(w(), [], [iso(4)], now))                      # user turn after it finished
        self.assertTrue(L.stale_action(w("resume"), merged, [], now))                # later worker merged
        self.assertFalse(L.stale_action(w(), [], [], now))                           # old but nobody moved on: still pending
        self.assertFalse(L.stale_action(w(), [], [iso(6)], now))                     # only turns before it finished
        self.assertFalse(L.stale_action(w(h=1), merged, [iso(0.5)], now))            # younger than ACTION_STALE_H
        self.assertFalse(L.stale_action(w("merge"), merged, [iso(4)], now))          # unmerged commits stay a todo

    def test_arg_error_wrong_name_hint(self):  # real log: session {"sid": ...} -> "missing argument 'id_or_name'"
        with self.assertRaises(L.ArgError) as c:
            L.call_tool("session", {"sid": "e3073449"})
        self.assertIn('got \'sid\': pass {"id_or_name": "e3073449"} instead', str(c.exception))

    def test_arg_error_unknown_and_bool(self):  # real log: mcp_status {"verbose": "true"} on a server predating verbose
        self.assertFalse(L.call_tool("mcp_status", {"verbose": True})[0])
        with self.assertRaises(L.ArgError) as c:
            L.call_tool("mcp_status", {"verbose": "true"})
        self.assertIn("JSON boolean", str(c.exception))
        with self.assertRaises(L.ArgError) as c:
            L.call_tool("mcp_status", {"verbos": True})
        self.assertIn("verbose (boolean)", str(c.exception))
        self.assertIn("restart", str(c.exception))
        with self.assertRaises(L.ArgError) as c:
            L.call_tool("mcp_status", {"verbose": "true"})
        self.assertIn('pass {"verbose": true} or false', str(c.exception))
        with self.assertRaises(L.ArgError) as c:
            L.call_tool("mcp_status", {"verbos": True})
        self.assertIn('did you mean \'verbose\'? pass {"verbose": true}', str(c.exception))
        with self.assertRaises(L.ArgError) as c:
            L.call_tool("agents", {"limit": 0})
        self.assertIn('e.g. {"limit": 1}', str(c.exception))

    def test_find_session_sid_fast_path(self):  # sid/prefix summarizes only that transcript (real: agents cold 1.3 s from scanning all)
        calls = []
        orig, saved_all = L.summarize, L.all_sessions
        L.summarize = lambda *a: calls.append(a[0]) or orig(*a)
        L.all_sessions = lambda *a: self.fail("sid lookup scanned every session")
        try:
            self.assertEqual(L.find_session(SID[:8])["name"], "alpha")
            self.assertEqual(L.find_session(SID)["sid"], SID)
        finally:
            L.summarize, L.all_sessions = orig, saved_all
        self.assertEqual(calls, [SID, SID])
        self.assertEqual(L.find_session("alpha")["sid"], SID)  # names still go through all_sessions

    def test_stale_code(self):  # real: an orchestrator's MCP kept the old live.py and answered "unknown argument verbose"
        saved = L._STARTED
        try:
            self.assertIsNone(L._stale())
            L._STARTED = os.path.getmtime(L.__file__) - 120  # file edited 2 min after this process started
            s = L._stale()
            self.assertRegex(s, r"^live\.py changed at \d\d:\d\d after this server started at \d\d:\d\d; restart the MCP")
            d = self.call("mcp_status", {"verbose": True})
            self.assertTrue(d["server"]["stale"]); self.assertEqual(d["stale"], s)
            with self.assertRaises(L.ArgError) as c:
                L.call_tool("mcp_status", {"verbos": True})
            self.assertIn(s, str(c.exception))
        finally:
            L._STARTED = saved

    def test_agents_harness_worktree(self):  # isolation: "worktree" workers: path only in meta worktreePath or transcript cwd, not the prompt
        import subprocess
        g = lambda d, *a: subprocess.run(["git", "-C", d, *a], check=True, capture_output=True, text=True).stdout
        ci = ("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty")
        repo = os.path.join(self.tmp.name, "gitrepo")
        os.makedirs(repo); g(repo, "init", "-q", "-b", "main"); g(repo, *ci, "-m", "base")
        subs = os.path.join(self.tmp.name, "projects", "p1", SID, "subagents")
        wts = {}
        for i, how in enumerate(("meta", "cwd")):
            aid = f"cafe100{i}"
            w = wts[how] = os.path.join(repo, ".claude", "worktrees", f"agent-{aid}")
            g(repo, "worktree", "add", "-q", "-b", f"worktree-agent-{aid}", w)
            g(w, "checkout", "-q", "-b", f"wt/{how}"); g(w, *ci, "-m", how)  # worker branches off inside the harness worktree
            rows = [{"type": "user", "timestamp": now_iso(-300 + i), "isSidechain": True, **({"cwd": w} if how == "cwd" else {}),
                     "message": {"content": "Fix the bug, then commit."}}, asst(f"h{i}", text="committed abc1234")]
            with open(os.path.join(subs, f"agent-{aid}.jsonl"), "w") as h:
                h.writelines(json.dumps(x, separators=(",", ":")) + "\n" for x in rows)
            if how == "meta":
                json.dump({"description": "d", "worktreePath": w, "worktreeBranch": f"worktree-agent-{aid}"}, open(os.path.join(subs, f"agent-{aid}.meta.json"), "w"))
        ws = {w["id"]: w for w in self.call("agents", {"session": "alpha", "all": True})["agents"][1:]}
        for i, how in enumerate(("meta", "cwd")):
            self.assertEqual(ws[f"cafe100{i}"]["wt"], {"path": wts[how], "branch": f"wt/{how}", "ahead": 1, "dirty": 0, "merged": False})

    def test_call_log_both_paths(self):
        self.call("method", {})
        self.assertTrue(L.call_tool("method", {"id": "nope"})[0])
        with self.assertRaises(L.ArgError):
            L.call_tool("overview", {"bogus": 1})
        msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "method", "arguments": {"id": "state.v1"}}}
        L.serve(io.StringIO(json.dumps(msg) + "\n"), io.StringIO())
        spec2 = importlib.util.spec_from_file_location("otm_serve", os.path.join(REPO, "05-dashboards", "live", "serve.py"))
        S = importlib.util.module_from_spec(spec2); spec2.loader.exec_module(S)
        self.assertEqual(S.api("method", "id=burn_ratio.v1")[0], 200)
        log = self._log()
        self.assertEqual([(r["tool"], r["via"], r["ok"]) for r in log],
                         [("method", "api", True), ("method", "api", False), ("overview", "api", False), ("method", "mcp", True), ("method", "api", True)])
        r = log[0]
        self.assertEqual(set(r), {"ts", "tool", "args", "ms", "chars", "ok", "via"})
        self.assertGreater(r["chars"], 100)
        self.assertIn("err", log[1]); self.assertIn("ArgError", log[2]["err"])
        self.assertEqual(log[4]["args"], '{"id":"burn_ratio.v1"}')
        L.CALLS_MAX_LINES, saved = 10, L.CALLS_MAX_LINES  # trimming keeps the newest half
        try:
            for _ in range(200):
                L.log_call({"ts": now_iso(), "tool": "x", "args": "y" * 100})
        finally:
            L.CALLS_MAX_LINES = saved
        self.assertLessEqual(len(self._log()), 10)
        os.environ["OTM_DATA_DIR"] = "/proc/nope"  # unwritable log never breaks the call
        self.call("method", {})

    def test_mcp_status(self):
        proj = os.path.join(self.tmp.name, "projects", "p1")
        with open(os.path.join(proj, SID + ".jsonl"), "a") as h:
            h.write(json.dumps(asst("m4", tool=("mcp__otm-live__overview", {}))) + "\n")
            h.write(json.dumps(asst("m5", tool=("mcp__otm-live__agents", {"all": True}))) + "\n")
        with open(os.path.join(proj, SID, "subagents", f"agent-{AID}.jsonl"), "a") as h:
            h.write(json.dumps(asst("s3", tool=("mcp__otm-live__overview", {}))) + "\n")
        self.call("method", {})
        L.serve(io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "method", "arguments": {"id": "x"}}}) + "\n"), io.StringIO())
        c = self.call("mcp_status", {"hours": 2})  # default compact: used tools only, 5 recent rows without args
        self.assertEqual(set(c), {"server", "window_h", "calls", "errors", "tools", "orchestrators", "recent", "unused"})
        self.assertEqual([t["name"] for t in c["tools"]], ["method"])
        self.assertEqual(sorted(c["unused"]), sorted(n for n in L.FUNCS if n != "method"))
        self.assertNotIn("args", c["recent"][0])
        d = self.call("mcp_status", {"hours": 2, "verbose": True})
        self.assertEqual(set(d), {"server", "window_h", "calls", "errors", "tools", "orchestrators", "recent"})
        self.assertEqual(set(d["server"]), {"name", "pid", "started", "version", "log", "stale"})
        self.assertFalse(d["server"]["stale"]); self.assertNotIn("stale", d)
        self.assertEqual((d["server"]["name"], d["server"]["pid"], d["window_h"], d["calls"], d["errors"]), ("otm-live", os.getpid(), 2, 3, 1))
        self.assertTrue(d["server"]["log"].endswith("live/calls.jsonl"))
        self.assertEqual(sorted(t["name"] for t in d["tools"]), sorted(L.FUNCS))
        t = d["tools"][0]
        self.assertEqual(set(t), {"name", "calls", "errors", "p50_ms", "p95_ms", "avg_chars", "max_chars", "last"})
        self.assertEqual((t["name"], t["calls"], t["errors"]), ("method", 2, 1))
        self.assertEqual(d["tools"][-1]["calls"], 0)
        o, = d["orchestrators"]
        self.assertEqual((o["sid"], o["name"], o["calls"], o["tools"]), (SID[:8], "alpha", 3, {"overview": 2, "agents": 1}))
        self.assertEqual([(r["via"], r["ok"]) for r in d["recent"]], [("api", True), ("mcp", False), ("api", True)])
        self.assertEqual(set(d["recent"][0]), {"ts", "tool", "via", "ms", "chars", "ok", "args"})
        self.assertEqual(self._log()[-1]["tool"], "mcp_status")

    def test_who_touches_declare_method(self):
        w = self.call("who_touches", {"path": os.path.join(self.repo, "src")})
        self.assertEqual([(r["node"], r["kind"]) for r in w["touched"]], [("main", ["edit"])])
        self.assertEqual([r["node"] for r in self.call("who_touches", {"path": self.repo})["touched"]].count(AID), 1)  # Grep path
        self.assertEqual(self.call("who_touches", {"port": 7845})["touched"][0]["kind"], ["cmd"])
        d = self.call("declare", {"goal": "refactor", "claims": [os.path.join(self.repo, "src")], "caller": "other"})
        self.assertEqual(d["declared"]["goal"], "refactor")
        self.assertEqual(len(d["overlaps"]), 0)  # caller 'other' has no transcript: overlap is listed in overview, not as mine
        self.assertIn("burn_ratio.v1", self.call("method", {}))
        self.assertTrue(L.call_tool("method", {"id": "nope"})[0])

    def test_fit_trims_longest_list(self):
        d = L.fit({"a": list(range(5000)), "b": [1, 2]})
        self.assertEqual(d["truncated"], {"a": 5000})
        self.assertLessEqual(L.size_tokens(d), L.MAX_RESPONSE_TOKENS)

    def test_jsonrpc(self):
        out = io.StringIO()
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "overview", "arguments": {"bogus": 1}}},
                {"jsonrpc": "2.0", "id": 3, "method": "nope"},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "method", "arguments": {"id": "state.v1"}}}]
        L.serve(io.StringIO("".join(json.dumps(m) + "\n" for m in msgs)), out)
        r = [json.loads(l) for l in out.getvalue().splitlines()]
        self.assertIn("record", [t["name"] for t in r[0]["result"]["tools"]])
        self.assertEqual((r[1]["error"]["code"], r[2]["error"]["code"]), (-32602, -32601))
        self.assertFalse(r[3]["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
