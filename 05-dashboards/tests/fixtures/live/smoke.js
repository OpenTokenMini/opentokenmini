// usage: node smoke.js index.html [deeplink|404] -> runs the live page script against a stub DOM and canned /api answers, clicks a session then a subagent
// modes: "" = normal; deeplink = page opened with ?open=&node=&more=&legend; 404 = mcp_status and orch_ux missing
const fs = require("fs"), path = require("path");
const MODE = process.argv[3] || "";
const code = fs.readFileSync(process.argv[2], "utf8").match(/<script>([\s\S]*)<\/script>/)[1];
const els = {};
const el = (id) => els[id] || (els[id] = { id, innerHTML: "", textContent: "", value: "", style: {}, dataset: {}, classList: { toggle() {}, add() {}, remove() {} },
  getBoundingClientRect: () => ({}), querySelectorAll: () => [], showModal() { this.shown = true; }, focus() {}, after() {} });
const OVERVIEW = { since: null, delta: null, quota: { "5h": { pct: 42, resets: "Sun 09:49" }, "7d": { pct: 95, resets: "Sun 18:59" }, age_min: 0 },
  measured: { sessions: [
    { name: "alpha", sid: "aaaa1111", state: "working", cost: 7.6, ctx_k: 53, last: new Date().toISOString(), touching: ["src/"], goal: "ship it", goal_src: "inferred",
      subagents: ["Live view | opus-5-5 | ctx 41k | $0.26 | 1m | Bash | running", "+1 more (session tool)"] },
    ...Array.from({ length: 6 }, (_, i) => ({ name: "s" + i, sid: "bbbb000" + i, state: "dead", cost: 0.1, ctx_k: 5, last: "2026-10-25T10:00Z", touching: [], subagents: [] }))],
    unchanged: 0 },
  inferred: [{ issue: "low_return", session: "alpha", node: "n2", method: "burn_ratio.v1" }, { issue: "overlap", a: "alpha", b: "s0", on: ["src/x.py"], method: "overlap.paths.v1" }],
  ledger: ["2026-10-25T12:00Z item1 otm-worker star 7d 20->21 tok 1000 tests True accepted True"] };
const SESSION = { name: "alpha", sid: "aaaa1111-full", state: "working", measured: { files: [{ path: "src/x.py", kind: "edit", last: "2026-10-25T12:00Z" }], files_total: 1,
  nodes: [{ node: "n1abc", desc: "Live view", model: "claude-opus-5-5", status: "running", dur_s: 60 }, { node: "n2", desc: "Old task", model: "claude-haiku", status: "done", dur_s: 600 }], nodes_total: 2 } };
const NODE = { kind: "subagent", node: "n1abc", type: "general-purpose", model: "claude-opus-5-5", models: ["claude-opus-5-5"], tok: { in: 1, cw: 2000, cr: 9000, out: 500 },
  returned: 1200, dur_s: 60, status: "running", tools: { Bash: 3 }, turns: 2, excerpt: "EXCERPT-OK" };
const fx = (f) => JSON.parse(fs.readFileSync(path.join(__dirname, "../../../live", f), "utf8"));
const AGENTS = fx("agents-fixture.json"), MCP = fx("mcp-fixture.json"), UX = fx("orch-ux-fixture.json");
const shift = Date.now() - Date.parse("2026-10-25T12:30:00Z");  // newest activity = now: "Fix pipeline tests" idle 18 min
for (const a of AGENTS.agents) for (const k of ["started", "last"]) a[k] = new Date(Date.parse(a[k]) + shift).toISOString();
const MANY = { ...AGENTS, agents: [...AGENTS.agents, ...["b1", "b2", "b3", "b4"].map((id, i) => ({ ...AGENTS.agents[1], id, desc: "Extra " + id, last: new Date(Date.now() - 6e5 * (i + 1)).toISOString() }))] };
const TRIM = { ...MANY, agents: MANY.agents.slice(0, 6), omitted: MANY.agents.length - 6 };  // live.py without all: main + 5, rest omitted
const seen = [];
let errs = 0;
global.document = { getElementById: el, querySelector: (s) => el(s), querySelectorAll: () => [], addEventListener() {}, hidden: false, body: { classList: { toggle() {} } } };
const urls = [];
global.location = { hash: "#live", pathname: "/", search: MODE === "deeplink" ? "?open=aaaa1111&node=a3&more=agents,mcp-recent&legend" : "" };
global.history = { replaceState: (a, b, u) => urls.push(u) };
const store = {}; global.localStorage = { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = v; } };
global.addEventListener = () => {}; global.setInterval = () => {}; global.PerformanceObserver = class { observe() {} };
const json = (d, ok = true) => ({ ok, status: ok ? 200 : 404, json: async () => d });
global.fetch = async (u, o) => {
  seen.push(u);
  if (o && o.method === "POST") return json({});
  if (u === "data.json") return json({ day: "last 24h", hours: [{ h: 1, cost: 1, vol: 10 }], sessions: [] });
  if (u.startsWith("api/overview?")) return json(OVERVIEW);
  if (u.startsWith("api/session?")) return json(SESSION);
  if (u.startsWith("api/node?")) return json(NODE);
  if (u.startsWith("api/agents?session=aaaa1111")) return json(AGENTS);
  if (u.startsWith("api/agents?session=bbbb000")) {  // 1: full fast, trimmed slow (race); 2: full slow (view more on a trimmed list)
    const full = u.includes("all=true"), late = (ms, d) => new Promise((r) => setTimeout(() => r(json(d)), ms));
    return u.includes("bbbb0001") ? full ? json(MANY) : late(40, TRIM) : u.includes("bbbb0002") ? full ? late(60, MANY) : json(TRIM) : json({}, false);
  }
  if (u.startsWith("api/mcp_status?") && MODE !== "404") return json(MCP);
  if (u.startsWith("api/orch_ux?") && MODE !== "404") return json(UX);
  return json({ error: "nope" }, false);
};
const ce = console.error; console.error = (...a) => { errs++; ce(...a); }; console.warn = console.error;
const tick = () => new Promise((r) => setTimeout(r, 20));
const target = (sel, data) => ({ closest: (s) => s.split(", ").includes(sel) ? { dataset: data } : null });
eval(code);
const check = (what, ok) => { if (!ok) { errs++; console.log("FAIL", what); } };
const html = () => els.live.innerHTML;
const inl = () => html().split('<div class="lv-inl').slice(1);
(async () => {
  await tick();
  check("quota", html().includes("42%") && html().includes("resets Sun 18:59") && html().includes("var(--red)"));
  check("sessions capped", (html().match(/class="lv-row/g) || []).length === 5 && html().includes("View more (2)"));
  check("overlap", html().includes("both edit src/x.py"));
  check("ledger", html().includes("item1 otm-worker"));
  check("status: legend button + freshness", els.status.innerHTML.includes("data-legend") && /updated \d+s ago/.test(els.status.innerHTML) && els.status.innerHTML.includes("every 10s"));
  check("legend viewer", els["legend-body"].innerHTML.includes("session waiting") && els["legend-body"].innerHTML.includes("above 150k") && els["legend-body"].innerHTML.includes("orchestrator"));
  check("caller cursor", seen.some((u) => u.startsWith("api/overview?caller=panel-") && u.includes("full=true")));
  check("aux fetched", seen.some((u) => u.startsWith("api/mcp_status?")) && seen.some((u) => u.startsWith("api/orch_ux?")));
  if (MODE === "404") {
    check("mcp unavailable", html().includes("MCP status unavailable"));
    check("ux unavailable", html().includes("Orchestrator UX unavailable"));
    check("no orch badge", !html().includes('class="badge'));
  } else {
    check("mcp section", html().includes("overview") && html().includes("260") && !html().includes("MCP status unavailable"));
    check("ux section", html().includes("too long") && html().includes("Keep replies under 120 words") && html().includes('class="lv-strip"'));
    check("orch badge", /class="badge cur"[^>]*>orchestrator</.test(html()));
  }
  if (MODE === "deeplink") {
    check("deeplink opened", seen.includes("api/session?id_or_name=aaaa1111") && seen.some((u) => u.startsWith("api/agents?session=aaaa1111")));
    check("deeplink node", seen.includes("api/node?session=aaaa1111&node=a3"));
    check("deeplink legend", els.legend.shown === true);
    const u = urls[urls.length - 1] || "";
    check("deeplink url kept", u.includes("open=aaaa1111") && u.includes("node=a3") && u.includes("more=agents%2Cmcp-recent") && u.includes("legend") && u.endsWith("#live"));
    console.log("errors", errs); process.exit(errs ? 1 : 0);
  }
  // inline subs from the overview lines (agents not loaded): direct call on a session without /api/agents data
  const ov = inlineSubs(OVERVIEW.measured.sessions.map((x) => ({ ...x, sid: "zzzz9999" }))[0]);
  check("inline subs (overview)", ov.includes("Live view") && ov.includes("$0.26") && ov.includes("41k") && ov.includes("width:68%;background:var(--impact)") && ov.includes("1m"));
  check("outcome chips", !outChip({ state: "done", wt: { ahead: 0, dirty: 0, merged: true } }).includes(">to merge<") && outChip({ state: "running" }).includes(">running<") && outChip({ state: "done", wt: { ahead: 2, dirty: 1, merged: false } }).includes(">to merge<")
    && outChip({ state: "done", outcome: "partial", wt: { ahead: 2, merged: false } }).includes(">partial<") && outChip({ state: "error" }).includes(">error<") && outChip({ state: "done" }).includes(">done<")
    && outChip({ state: "running", wt: { ahead: 2 } }).includes(">running<"));
  const mg = outChip({ state: "done", wt: { branch: "wt/mcp14", ahead: 0, dirty: 0, merged: true } }), tm = outChip({ state: "done", wt: { branch: "wt/dash13", ahead: 2, dirty: 0, merged: false } });
  check("wt tags", mg.includes(">mcp14<") && mg.includes(">merged<") && !mg.includes(">to merge<") && tm.includes(">dash13<") && tm.includes(">to merge<") && !tm.includes(">merged<")
    && outChip({ state: "done", wt: { branch: "wt/x", ahead: 0, dirty: 2, merged: true } }).includes(">dirty<") && !outChip({ state: "done", wt: null }).includes("lv-flag")
    && outChip({ state: "done", next: "merge", wt: { branch: "wt/x", ahead: 1, merged: false } }).split(">to merge<").length === 2 && el("legend-body").innerHTML.includes(">merged<") && el("legend-body").innerHTML.includes(">dirty<"));
  const ord = [{ state: "done", last: "3", wt: { merged: true } }, { state: "done", last: "1", wt: { ahead: 1, merged: false } }, { state: "running", last: "0" }, { state: "done", last: "2", wt: { dirty: 1, merged: true } }].sort(byNeed).map((r) => r.last).join("");
  check("wt sort", ord === "0213");
  check("mcp zero-call tool hidden", MODE === "404" || !html().includes(">method<"));
  els.live.onclick({ target: target("[data-turn]", { turn: "all|3" }) });
  check("turn click detail", MODE === "404" || html().includes('class="lv-turn"') && html().includes("user: ") && html().includes('class="on" data-turn="all|3"'));
  els.live.onclick({ target: target("[data-turn]", { turn: "all|3" }) });
  check("turn click toggles", MODE === "404" || !html().includes('class="lv-turn"'));
  check("ctx bar bands", ctxBar(41).includes("var(--impact)") && ctxBar(55).includes("var(--amber)") && ctxBar(61).includes("var(--red)") && ctxBar(180).includes("width:100%") && ctxBar(undefined).includes("—"));
  check("paths one slash", shortPath("//tmp/claude-1000", "/home/u/p") === "/tmp/claude-1000" && shortPath("/worktrees/agent-ae78d865b4ae/06-optional/mcp-server", "/home/u/p") === "wt ae78d865/06-optional/mcp-server"
    && shortPath("/home/u/p//src/x.py", "/home/u/p/") === "src/x.py" && !/\/\//.test(shortPath("//home/u//a", "/home/u")));
  check("no done chip with wt tag", !outChip({ state: "done", wt: { branch: "wt/x", merged: true, ahead: 0, dirty: 0 } }).includes(">done<") && outChip({ state: "done", wt: { branch: "wt/x", merged: true } }).includes(">merged<")
    && outChip({ state: "done" }).includes(">done<") && outChip({ state: "running", wt: { branch: "wt/x", dirty: 2 } }).includes(">running<"));
  check("ctx bar tooltip", ctxBar(55).includes("amber >50k"));
  // inline subs from /api/agents: running first, chips on finished workers, result on hover, missing fields render cleanly
  const rows = inl();
  check("inline subs running first", rows.length === 4 && rows[0].includes("var(--impact)") && rows[1].includes("var(--impact)") && rows[3].includes("View more (3)"));
  check("inline ctx bar red", rows.some((r) => r.includes("Live delegation view") && r.includes("width:100%;background:var(--red)") && r.includes("180k")));
  check("inline no undefined", !html().includes("undefined") && !html().includes("NaN"));
  els.live.onclick({ target: target("[data-inl]", { inl: "aaaa1111" }) });
  const all = inl().join("");
  check("inline view more", inl().length === 7 && all.includes(">running<") && all.includes(">to merge<") && all.includes(">error<") && all.includes(">partial<") && all.includes("Show less") && all.includes('data-less="1"'));
  check("inline tag", />Grep usages<span[^]*?>inline</.test(all) && all.includes('data-wk="a3"') && all.includes("result: Found 9 call sites"));
  els.live.onclick({ target: target("[data-inl]", { inl: "aaaa1111", less: "1" }) });
  check("inline show less", inl().length === 4);
  els.live.onclick({ target: target("[data-wk]", { sid: "aaaa1111", wk: "a3" }) }); await tick();
  check("inline worker click", seen.includes("api/node?session=aaaa1111&node=a3") && html().includes('class="lv-ag on"') && (urls[urls.length - 1] || "").includes("node=a3"));
  els.live.onclick({ target: target(".lv-row", { sid: "aaaa1111" }) }); await tick();
  els.live.onclick({ target: target(".lv-row", { sid: "aaaa1111" }) }); await tick();
  check("session fetched", seen.includes("api/session?id_or_name=aaaa1111"));
  check("workers unified", !html().includes("lv-sub") && !html().includes(">Delegation<") && html().includes(">Workers<") && !html().includes('class="lv-inl') && html().includes("Live view") && html().includes("41k") && html().includes("$0.26"));
  check("touching", html().includes("src/x.py") && html().includes("edit"));
  check("agents fetched", seen.includes("api/agents?session=aaaa1111&all=true"));
  check("agents header", html().includes("orchestrator") && html().includes("$4.20") && html().includes("$3.80") && html().includes("median ctx") && html().includes("41k"));
  check("to merge header", /<b>1<\/b><span>to merge<\/span>/.test(html()));
  AGENTS.totals.next = { resume: 2 }; lvRender();
  check("next header", /<b>2<\/b><span>to resume<\/span>/.test(html()) && !/<span>partial<\/span>/.test(html())); delete AGENTS.totals.next; lvRender();
  check("next chip + order", outChip({ state: "done", outcome: "partial", next: "resume", handoff: "/h.md" }).includes(">to resume<") && agRow({ state: "working" }).state === "running"
    && [{ state: "done", last: "9" }, { state: "done", next: "inspect", last: "1" }, { state: "done", next: "merge", last: "1" }, { state: "running", last: "0" }].sort(byNeed).map((r) => r.next || r.state).join() === "running,merge,inspect,done");
  check("stale chip", outChip(agRow({ state: "done", outcome: "partial", stale: "inspect" })).includes(">stale<") && !outChip({ state: "done", outcome: "partial", stale: "inspect" }).includes(">to inspect<"));
  check("workers running first", html().split('class="lv-ag"').slice(1, 4).every((r) => r.includes(">running<")) && html().includes("from Live delegation view"));
  check("agents flags", html().includes(">bloat<") && html().includes("stuck 18m") && !html().includes("stuck 1m"));
  check("agents capped", (html().match(/class="lv-ag"/g) || []).length === 5 && html().includes('data-more="agents">View more (3)'));
  els.live.onclick({ target: target("[data-more]", { more: "agents" }) });
  check("agents view more", (html().match(/class="lv-ag"/g) || []).length === 8 && html().includes("Old task") && html().includes("low return") && html().includes("Grep usages"));
  els.live.onclick({ target: target("[data-node]", { node: "n1abc" }) }); await tick();
  check("node fetched", seen.includes("api/node?session=aaaa1111&node=n1abc"));
  check("node detail", html().includes("EXCERPT-OK") && html().includes("11k"));
  check("node detail once", (html().match(/EXCERPT-OK/g) || []).length === 1);
  els.live.onclick({ target: target("[data-node]", { node: "a3" }) }); await tick();
  check("worker click", seen.includes("api/node?session=aaaa1111&node=a3") && html().includes('class="lv-ag on"') && html().includes("wt/grep · 2 ahead") && html().includes("EXCERPT-OK"));
  check("url synced", (urls[urls.length - 1] || "").includes("open=aaaa1111") && (urls[urls.length - 1] || "").includes("node=a3"));
  els.live.onclick({ target: target(".lv-row", { sid: "bbbb0000" }) }); await tick();
  check("agents 404 falls back to nodes", !html().includes("median ctx") && html().includes("Old task"));
  els.live.onclick({ target: target("[data-more]", { more: "sessions" }) });
  check("view more", (html().match(/class="lv-row/g) || []).length === 7 && html().includes("Show less"));
  const ags = () => (html().match(/class="lv-ag"/g) || []).length;  // MANY: 10 workers + 2 session nodes = 12 rows
  lvAgents("bbbb0001", false); els.live.onclick({ target: target(".lv-row", { sid: "bbbb0001" }) }); await new Promise((r) => setTimeout(r, 80));
  els.live.onclick({ target: target("[data-more]", { more: "agents" }) });
  check("trimmed reply after full keeps full", ags() === 12 && html().includes("Extra b4"));
  lvAgents("bbbb0002", false); await tick(); els.live.onclick({ target: target(".lv-row", { sid: "bbbb0002" }) }); await tick();
  check("omitted counted in view more", ags() === 5 && html().includes('data-more="agents">View more (7)'));
  els.live.onclick({ target: target("[data-more]", { more: "agents" }) }); await new Promise((r) => setTimeout(r, 100));
  check("view more reaches omitted", ags() === 12 && html().includes("Extra b4") && seen.filter((u) => u === "api/agents?session=bbbb0002&all=true").length === 2);
  console.log("errors", errs); process.exit(errs ? 1 : 0);
})();
