#!/usr/bin/env python3
"""Live orchestrator MCP server (stdio, JSON-RPC 2.0, one message per line) over the agent sessions running on this machine.

Tools: overview session agents node who_touches declare method record. Reads Claude Code's session registry, transcripts and subagent
transcripts (read-only, incremental, capped per file) and the bgjobs quota cache; never hits the network.
Writes only cursors and declarations under <data dir>/live/ and the delegation ledger <data dir>/delegations.jsonl. Usage: mcp-server/AGENTS.md, design: orchestrator-interface.md.
"""
import argparse, difflib, glob, json, os, re, subprocess, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from datetime import datetime, timedelta, timezone

import pathlib  # numbered stage dirs aren't importable: find the repo, put 02-measure/ and this dir on sys.path
REPO = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir())
sys.path.insert(0, str(REPO / "02-measure"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from schemas.config import load_config, data_dir
from schemas.cost import load_prices, make_tokens, list_cost, price_for
from server import ToolError, ArgError, PROTOCOL_VERSIONS, MAX_RESPONSE_TOKENS, size_tokens, _ok, _err

CLAUDE_DIR = os.path.expanduser("~/.claude")
SESSIONS_DIR = os.path.join(CLAUDE_DIR, "sessions")    # <pid>.json live process registry
PROJECTS_DIR = os.path.join(CLAUDE_DIR, "projects")    # <project>/<sid>.jsonl + <sid>/subagents/agent-<id>.jsonl(.meta.json)
QUOTA_CACHE = "/run/user/1000/bgjobs/quota_cache.json"  # written by bgjobs; missing -> quota: null
QUOTA_STALE_MIN = 15        # quota cache older than this -> stale: true
DEFAULT_WINDOW_H = 6        # overview: sessions live now or with transcript activity in the last N hours
LOOKUP_WINDOW_H = 24 * 7    # session/node/who_touches: how far back names and ids are searched
MAX_SCAN_BYTES = 32 << 20   # per transcript: only the last N bytes are ever parsed (cost then marked partial)
HEAD_BYTES = 256 << 10      # bytes read from the start of a partially scanned transcript to find its goal
WAITING_S = 1800            # idle for less than this after a turn -> waiting_user, else idle
SUB_ACTIVE_S = 300          # subagent transcript written within N s and not ended -> active
GOAL_CHARS = 60             # goal excerpt in overview
SESSION_GOAL_CHARS = 160    # goal excerpt in session
EXCERPT_CHARS = 80          # prompt excerpt per turn
RESULT_EXCERPT_CHARS = 400  # final result excerpt in node
KEEP_TEXT_CHARS = 2000      # last assistant text kept per turn in memory
TOUCH_TOP = 3               # touching dirs per session in overview
DIR_DEPTH = 2               # touching dir = repo label + first N dirs inside the repo
REPO_LABEL_PARTS = 2        # repo label = last N components of the git root
RECENT_TURNS = 5            # turns in session
SESSION_FILES = 10          # files in session
SESSION_NODES = 12          # subagents in session (limit arg overrides turns/files/nodes caps)
ID_CHARS = 8                # subagent ids shown (node lookups match by prefix)
DESC_CHARS = 60             # agents: desc excerpt
AGENTS_ROWS = 20            # agents: newest workers listed by default (~75 tok each; limit arg overrides)
AGENTS_CURSORS_KEEP = 8     # agents since=: worker snapshots kept per session (one per heartbeat cursor)
AGENTS_RECENT_DONE = 5      # agents (all=false): finished workers kept besides main + running; rest counted in omitted
AGENT_RESULT_CHARS = 200    # agents: worker result excerpt (final text, whitespace collapsed)
WT_CACHE_S = 10             # agents: git facts of a running worker's worktree cached this long (panel polls)
ACTION_STALE_H = 2          # agents: inspect/resume older than this, with a later user turn or later merged worker -> "stale" (not counted in next)
WT_DONE_CACHE_S = 600       # agents: finished worker's worktree: reused while git HEAD/index/refs mtimes are unchanged, at most this long
D1_URL = "http://localhost:6975/ask"  # local decision model: outcome of a worker whose final text the keywords can't settle
D1_TIMEOUT_S = 1            # any d1 failure disables it for the process (keyword fallback)
D1_MIN_P = 0.6              # d1 answers below this confidence fall back to keywords
HANDOFF_DIR = f"/tmp/claude-{os.getuid()}/handoffs"  # agents: <dir>/<full agent id>.md counts as a worker's handoff even if its report omits it
OUTCOME_TEXT_CHARS = 400    # head of a worker's final text judged for outcome (reports lead with it; tails quote other things)
GIT_TIMEOUT_S = 2           # agents: per git subprocess; any failure -> wt null
GIT_THREADS = 8             # agents: worktrees refreshed in parallel (a main-repo commit invalidates every finished one at once)
WT_PROMPT_CHARS = 8000      # agents: head of a worker's first prompt searched for worktree paths
CALLS_MAX_LINES = 20000     # live/calls.jsonl: trimmed to the newest half once it grows past this many lines
CALLS_ARGS_CHARS = 120      # calls.jsonl: args excerpt
STATUS_RECENT = 20          # mcp_status verbose: newest calls listed
STATUS_RECENT_COMPACT = 5   # mcp_status default: newest calls listed (no args; tools with 0 calls only named in unused)
STATUS_ORCH = 10            # mcp_status: newest orchestrator sessions listed
MCP_PREFIX = "mcp__otm-live__"  # tool_use name prefix of this server's tools in Claude Code transcripts
WHO_ROWS = 20               # rows in who_touches
DELTA_MIN_COST = 0.5        # USD: smaller cost changes are not reported in delta
LOW_RETURN_MIN_BURN_K = 30  # burn_ratio.v1: only subagents that burned at least N k fresh tokens
LOW_RETURN_CHARS_PER_K = 10 # burn_ratio.v1: flagged when returned chars per burned k token is below this
OVERLAP_MAX = 5             # overlap items in overview
SUB_LINES = 5               # subagent lines per session in overview (newest in window)
LEDGER_LINES = 3            # last delegation ledger lines in overview
SKIP_PROMPTS = ("<system-reminder>", "[SYSTEM NOTIFICATION", "<local-command", "<task-notification>", "<command-", "Caveat:", "[Request interrupted")
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
READ_TOOLS = {"Read", "Grep", "Glob", "NotebookRead"}
PORT_RE = re.compile(r"(?:--port[= ]|-p\s+|localhost:|127\.0\.0\.1:|0\.0\.0\.0:|http\.server\s+)(\d{2,5})\b")
ABS_PATH_RE = re.compile(r"(?<![\w.~])(/[\w.\-/]+)")
SERVER_INFO = {"name": "otm-live", "version": "0.1"}
AGG = ("cost = sum over distinct assistant message ids of transcript usage x 02-measure/schemas/prices.json list price, "
       "main + subagent transcripts, since session start (partial if a transcript exceeds MAX_SCAN_BYTES); "
       "ctx = context of the last assistant turn; last = newest transcript write")
METHODS_DOC = {
    "agg.v1": AGG,
    "agents.v1": "agents: one row per agent of a session (main first, then subagent transcripts by start). cost/turns from distinct "
                 "assistant message ids x prices.json; turns = model calls; ctx_k = last call context, peak_ctx_k = max; state working "
                 "(written < SUB_ACTIVE_S ago, not ended), done (result received or end_turn; main: process gone), else idle; parent = "
                 "meta parentAgentId (nested) else the main agent. Telemetry has no subagent split, so this is transcript-only.",
    "state.v1": "working if registry status busy or a subagent is active; waiting_user if status idle/waiting for < WAITING_S since "
                "its last change; idle after that; dead if the pid is gone (working if the transcript was written < SUB_ACTIVE_S ago). "
                "Inputs: ~/.claude/sessions/<pid>.json, transcript mtimes.",
    "touching.v1": "directories of files passed to Edit/Write/MultiEdit/NotebookEdit tool calls (main + running subagents) in the window, "
                   "as <git root label>/<first DIR_DEPTH dirs>, most edits first. Bash writes are not counted.",
    "goal.first_prompt.v1": "first user prompt of the transcript that is not injected (system reminders, commands, task "
                            "notifications), truncated; replaced by the declared goal when the session called declare.",
    "overlap.paths.v1": "two sessions in the window whose edited files (Edit/Write tool inputs) intersect, or whose declared "
                        "claims are a path prefix of the other's edits or claims. Window: window_h.",
    "burn_ratio.v1": "ended subagent with fresh tokens (input + cache write + output, cache reads excluded) >= LOW_RETURN_MIN_BURN_K k "
                     "and returned chars / burned k < LOW_RETURN_CHARS_PER_K. Returned = final result text the parent received. "
                     "Exempt: workers that delivered a commit (hash cited in the result, or worktree merged / ahead > 0).",
    "port.v1": "who_touches port: the live process listening on it (/proc/net/tcp*, fd inode) walked up to a registered "
               "Claude Code pid, plus Bash commands mentioning it (--port N, -p N, localhost:N, http.server N).",
    "delta.v1": "per caller cursor (CLAUDE_CODE_SESSION_ID or caller argument) under <data dir>/live/cursors.json: new or gone "
                "sessions, state changes, cost increase >= DELTA_MIN_COST, new touching dirs since the caller's last overview.",
}

_PRICES = None
_SCANS = {}   # path -> incremental scan state
_ROOTS = {}   # dir -> git root or ""
_WT = {}      # worktree path -> (time, git facts or None), WT_CACHE_S


# ---- transcript scanning ---------------------------------------------------------------------------------------

def _new_scan():
    return {"off": 0, "partial": False, "msgs": {}, "turns": [], "touch": {}, "tools": Counter(), "titles": {},
            "agents": {}, "last_ctx": 0, "peak_ctx": 0, "last_tool": None, "first_ts": None, "last_ts": None, "last_event": None, "work_ts": None, "goal": None, "cwd": None, "paths": []}


def _text(content):
    if isinstance(content, str):
        return content
    return " ".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def _prompt(text):
    """A typed user prompt, or None for injected text."""
    t = (text or "").strip()
    return t if t and not t.startswith(SKIP_PROMPTS) else None


def _touch(st, key, kind, ts):
    prev = st["touch"].get(key)
    n = prev[2] + 1 if prev else 1
    k = "edit" if kind == "edit" or (prev and prev[0] == "edit") else kind
    st["touch"][key] = (k, max(ts or "", prev[1] if prev else ""), n)


def _line(st, d, main):
    t, ts = d.get("type"), d.get("timestamp")
    if t in ("custom-title", "ai-title", "agent-name"):
        st["titles"][t] = d.get({"custom-title": "customTitle", "ai-title": "aiTitle", "agent-name": "agentName"}[t])
        return
    if main and d.get("isSidechain"):
        return
    if ts:
        st["first_ts"] = st["first_ts"] or ts
        st["last_ts"] = ts
    if d.get("cwd") and not st["cwd"]:
        st["cwd"] = d["cwd"]
    if t == "assistant":
        m = d.get("message") or {}
        u, mid, model = m.get("usage") or {}, m.get("id"), m.get("model")
        if not st["turns"]:
            st["turns"].append(_new_turn(ts, None))
        turn = st["turns"][-1]
        turn["end"] = ts
        if mid and u and model != "<synthetic>":
            cc = u.get("cache_creation") or {}
            prev = st["msgs"].get(mid)
            out = max(int(u.get("output_tokens") or 0), prev[6] if prev else 0)
            st["msgs"][mid] = (len(st["turns"]) - 1, model, int(u.get("input_tokens") or 0), int(u.get("cache_creation_input_tokens") or 0),
                               int(u.get("cache_read_input_tokens") or 0), (cc.get("ephemeral_5m_input_tokens"), cc.get("ephemeral_1h_input_tokens")), out)
            st["last_ctx"] = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
            st["peak_ctx"] = max(st["peak_ctx"], st["last_ctx"])
        for b in m.get("content") or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and b.get("text", "").strip():
                turn["text"], turn["text_len"] = b["text"][:KEEP_TEXT_CHARS], len(b["text"])
            elif b.get("type") == "tool_use":
                name, i = b.get("name") or "?", b.get("input") or {}
                turn["tools"][name] += 1
                st["tools"][name] += 1
                st["last_tool"] = name
                if not isinstance(i, dict):
                    continue
                p = i.get("file_path") or i.get("notebook_path") or (i.get("path") if name in READ_TOOLS else None)
                if p and isinstance(p, str):
                    _touch(st, os.path.normpath(os.path.expanduser(p)), "edit" if name in EDIT_TOOLS else "read" if name in READ_TOOLS else "other", ts)
                if name == "Bash":
                    for port in PORT_RE.findall(str(i.get("command") or "")):
                        _touch(st, f"port:{port}", "cmd", ts)
        st["last_event"], st["work_ts"] = ("assistant", m.get("stop_reason")), ts or st["work_ts"]
    elif t == "user" and not d.get("isMeta") and not d.get("isCompactSummary"):
        c = (d.get("message") or {}).get("content")
        r = d.get("toolUseResult")
        if isinstance(r, dict) and r.get("agentId"):
            a = st["agents"].setdefault(r["agentId"], {})
            a.update({k: r[k] for k in ("status", "description", "agentType", "resolvedModel", "totalDurationMs", "totalTokens") if k in r})
            if r.get("status") == "completed":
                a["returned"] = len(_text(r.get("content")))
                a["result"] = _text(r.get("content"))[:RESULT_EXCERPT_CHARS]
        text = _text(c)
        if "<task-notification>" in text:
            for blk in re.findall(r"<task-notification>(.*?)</task-notification>", text, re.S):
                tid = re.search(r"<task-id>(.*?)</task-id>", blk)
                if not tid:
                    continue
                a = st["agents"].setdefault(tid.group(1), {})
                for k, rx in (("status", r"<status>(.*?)</status>"), ("totalDurationMs", r"<duration_ms>(\d+)</duration_ms>")):
                    mm = re.search(rx, blk, re.S)
                    if mm:
                        a[k] = int(mm.group(1)) if k == "totalDurationMs" else mm.group(1)
                res = re.search(r"<result>(.*?)</result>", blk, re.S)
                if res:
                    a["returned"], a["result"] = len(res.group(1).strip()), res.group(1).strip()[:RESULT_EXCERPT_CHARS]
        tr = not isinstance(c, str) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c or [])
        p = None if tr else _prompt(text)
        if p:
            if st["goal"] is None:  # first prompt: absolute paths, for worktree detection in agents
                st["asks_commit"] = bool(re.search(r"\bcommit", p, re.I))
                st["paths"] = list(dict.fromkeys(m.rstrip(".,;:)'\"`") for m in ABS_PATH_RE.findall(p[:WT_PROMPT_CHARS])))
            st["turns"].append(_new_turn(ts, p))
            st["goal"] = st["goal"] or p[:SESSION_GOAL_CHARS]
            st["last_event"], st["work_ts"] = ("user", "prompt"), ts or st["work_ts"]
        elif tr:
            st["last_event"], st["work_ts"] = ("user", "tool_result"), ts or st["work_ts"]
        # else injected text (reminders, task notifications appended after the end): not work, state untouched


def _new_turn(ts, prompt):
    return {"ts": ts, "end": ts, "prompt": " ".join((prompt or "").split())[:EXCERPT_CHARS], "chars": len(prompt or ""),
            "tools": Counter(), "text": "", "text_len": 0}


def scan(path, main=True):
    """Incremental parse of one transcript (only appended bytes are read again); state cached per path."""
    st = _SCANS.get(path)
    try:
        size = os.path.getsize(path)
    except OSError:
        return _new_scan()
    if st is None or size < st["off"]:
        st = _SCANS[path] = _new_scan()
    if st["off"] == 0 and size > MAX_SCAN_BYTES:
        st["off"], st["partial"] = size - MAX_SCAN_BYTES, True
        with open(path, "rb") as h:  # goal from the head; the scan starts mid-file
            for raw in h.read(HEAD_BYTES).decode(errors="replace").splitlines()[:-1]:
                if '"type":"user"' in raw:
                    try:
                        d = json.loads(raw)
                    except ValueError:
                        continue
                    if not d.get("isSidechain") and not d.get("isMeta") and _prompt(_text((d.get("message") or {}).get("content"))):
                        st["goal"] = _prompt(_text(d["message"]["content"]))[:SESSION_GOAL_CHARS]
                        break
    if size > st["off"]:
        with open(path, "rb") as h:
            h.seek(st["off"])
            buf = h.read()
        nl = buf.rfind(b"\n")
        if nl < 0:
            return st
        skip_first = st["partial"] and st["off"] == size - MAX_SCAN_BYTES and not st["turns"] and not st["msgs"]
        st["off"] += nl + 1
        lines = buf[:nl + 1].decode(errors="replace").splitlines()
        for raw in lines[1:] if skip_first else lines:
            if raw.startswith('{"type":"') and not raw.startswith(('{"type":"custom-title"', '{"type":"ai-title"', '{"type":"agent-name"', '{"type":"user"', '{"type":"assistant"')):
                continue  # api-request blobs, attachments, modes: large and irrelevant
            if not raw.startswith('{"type":"') and '"type":"assistant"' not in raw and '"type":"user"' not in raw:
                continue
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            if isinstance(d, dict):
                _line(st, d, main)
    return st


def _tokens(st, turn=None):
    t = {"in": 0, "cw": 0, "cr": 0, "out": 0}
    for ti, _, i, cw, cr, _, o in st["msgs"].values():
        if turn is None or ti == turn:
            t["in"] += i; t["cw"] += cw; t["cr"] += cr; t["out"] += o
    return t


def _cost(st):
    """List cost of a scan; memoized on the scan's read offset (msgs only change when scan() reads new bytes)."""
    global _PRICES
    key = (st.get("off"), len(st["msgs"]))
    if st.get("cost_at", (None,))[0] == key:
        return st["cost_at"][1]
    _PRICES = _PRICES or load_prices()
    c = 0.0
    for _, model, i, cw, cr, (w5, w1), o in st["msgs"].values():
        price = price_for(model, _PRICES)
        if price:
            c += list_cost(make_tokens(input=i, output=o, cache_read=cr, cache_write=cw, cache_write_5m=w5, cache_write_1h=w1), price)["total"]
    st["cost_at"] = (key, c)
    return c


def _models(st, turn=None):
    return sorted({m[1] for m in st["msgs"].values() if m[1] and (turn is None or m[0] == turn)})


# ---- sessions --------------------------------------------------------------------------------------------------

def _iso(ts):
    """Epoch seconds or ISO string -> 'YYYY-MM-DDTHH:MMZ' (UTC)."""
    if ts is None:
        return None
    if isinstance(ts, str):  # transcript ISO: honor any offset, naive = UTC
        try:
            d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
        ts = (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def registry():
    """Live Claude Code processes: sid -> registry record (pid alive)."""
    out = {}
    for f in glob.glob(os.path.join(SESSIONS_DIR, "*.json")):
        try:
            with open(f) as h:
                j = json.load(h)
        except (OSError, ValueError):
            continue
        if isinstance(j, dict) and j.get("sessionId") and j.get("pid") and os.path.exists(f"/proc/{j['pid']}"):
            out[j["sessionId"]] = j
    return out


def transcripts(window_h, live):
    """sid -> main transcript path: live sessions plus transcripts written within window_h."""
    cut, out = time.time() - window_h * 3600, {}
    for p in glob.glob(os.path.join(PROJECTS_DIR, "*", "*.jsonl")):
        sid = os.path.basename(p)[:-6]
        try:
            if sid in live or os.path.getmtime(p) >= cut:
                out[sid] = p
        except OSError:
            pass
    return out


def _subagent_files(path):
    return glob.glob(os.path.join(path[:-6], "subagents", "agent-*.jsonl"))


def _meta(f):
    try:
        with open(f[:-6] + ".meta.json") as h:
            return json.load(h)
    except (OSError, ValueError):
        return {}


def _active(st, mtime, now):
    return now - mtime < SUB_ACTIVE_S and st["last_event"] != ("assistant", "end_turn")


def _git_root(d):
    if d in _ROOTS:
        return _ROOTS[d]
    p, root = d, ""
    while p and p != "/":
        if os.path.exists(os.path.join(p, ".git")):
            root = p
            break
        p = os.path.dirname(p)
    _ROOTS[d] = root
    return root


def touch_dir(path, cwd):
    """File path -> short dir label: <git root label>/<first DIR_DEPTH dirs> (touching.v1)."""
    d = os.path.dirname(path)
    root = _git_root(d)
    if root:
        label = "/".join(root.split("/")[-REPO_LABEL_PARTS:])
        inner = os.path.relpath(d, root).split("/")
        inner = [] if inner == ["."] else inner[:DIR_DEPTH]
        return "/".join([label] + inner) + "/"
    rel = os.path.relpath(d, cwd) if cwd and d.startswith(cwd + "/") else d
    return "/".join(rel.split("/")[:DIR_DEPTH + 1]) + "/"


def session_state(reg, last_mtime, active_subs, now):
    if not reg:
        return "working" if now - last_mtime < SUB_ACTIVE_S else "dead"
    status = str(reg.get("status") or "")
    if status == "busy" or active_subs:
        return "working"
    since = now - (reg.get("statusUpdatedAt") or reg.get("updatedAt") or 0) / 1000
    if "wait" in status or since < WAITING_S:
        return "waiting_user"
    return "idle"


def summarize(sid, path, reg, now, cut):
    """One session: main + subagent scans and the derived overview fields."""
    st = scan(path)
    subs = []
    for f in _subagent_files(path):
        try:
            mt = os.path.getmtime(f)
        except OSError:
            continue
        subs.append((f, scan(f, main=False), mt))
    mtimes = [os.path.getmtime(path)] + [mt for _, _, mt in subs]
    active = sum(_active(s, mt, now) for _, s, mt in subs)
    cut_iso = _iso(cut)
    edits = Counter()
    files = {}
    for s, now_ in [(st, True)] + [(s, _active(s, mt, now)) for _, s, mt in subs]:
        for k, (kind, ts, n) in s["touch"].items():
            if kind == "edit" and (_iso(ts) or "") >= cut_iso:
                if now_:  # touching = now: a finished subagent's edits are done (still in edited/overlaps)
                    edits[touch_dir(k, st["cwd"] or (reg or {}).get("cwd"))] += n
                files[k] = ts
    res = {}
    for x in [st] + [x for _, x, _ in subs]:
        res.update(x["agents"])  # result/status each parent received, keyed by full agent id
    t = st["titles"]
    name = (reg or {}).get("name") or t.get("custom-title") or t.get("agent-name") or t.get("ai-title") or sid[:8]
    return {"sid": sid, "name": name, "path": path, "scan": st, "subs": subs, "reg": reg,
            "state": session_state(reg, max(mtimes), active, now), "cost": _cost(st) + sum(_cost(s) for _, s, _ in subs),
            "partial": st["partial"] or any(s["partial"] for _, s, _ in subs), "ctx": st["last_ctx"], "last": max(mtimes),
            "active": active, "touching": [d for d, _ in edits.most_common(TOUCH_TOP)], "edited": files, "res": res}


def all_sessions(window_h):
    now = time.time()
    live = registry()
    cut = now - window_h * 3600
    out = [summarize(sid, p, live.get(sid), now, cut) for sid, p in transcripts(window_h, live).items()]
    return sorted(out, key=lambda s: -s["last"])


def find_session(key, window_h=LOOKUP_WINDOW_H):
    key = (key or "").strip()
    if not key:
        raise ToolError("id_or_name is required")
    if re.fullmatch(r"[0-9a-f-]{8,36}", key):  # sid or unique sid prefix: summarize just that transcript, not every session (~1 s cold)
        m = glob.glob(os.path.join(PROJECTS_DIR, "*", glob.escape(key) + "*.jsonl"))
        if len({os.path.basename(f) for f in m}) == 1:
            sid, now = os.path.basename(m[0])[:-6], time.time()
            return summarize(sid, m[0], registry().get(sid), now, now - window_h * 3600)
    ss = all_sessions(window_h)
    for test in (lambda s: s["sid"] == key, lambda s: s["name"] == key, lambda s: s["sid"].startswith(key),
                 lambda s: key.lower() in s["name"].lower()):
        hit = [s for s in ss if test(s)]
        if hit:
            return hit[0]
    m = glob.glob(os.path.join(PROJECTS_DIR, "*", glob.escape(key) + "*.jsonl"))
    if m:
        sid = os.path.basename(m[0])[:-6]
        return summarize(sid, m[0], registry().get(sid), time.time(), time.time() - window_h * 3600)
    raise ToolError(f"no session matches {key!r} (searched names and ids in the last {window_h}h); call overview for names")


# ---- caller state (cursors, declarations) ----------------------------------------------------------------------

def _state_file(name):
    d = os.path.join(data_dir(load_config()), "live")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


def _load(name):
    try:
        with open(_state_file(name)) as h:
            return json.load(h)
    except (OSError, ValueError):
        return {}


def _save(name, obj):
    p = _state_file(name)
    with open(p + ".tmp", "w") as h:
        json.dump(obj, h)
    os.replace(p + ".tmp", p)


def caller_id(a):
    return a.get("caller") or os.environ.get("CLAUDE_CODE_SESSION_ID") or None


# ---- quota -----------------------------------------------------------------------------------------------------

def _reset_passed(resets, ts, now):
    """resets is bgjobs' local '%a %H:%M' (e.g. 'Sun 14:49'): its first occurrence at/after the cache ts (minute
    precision) is the reset instant; True once now is past it. Unparseable ('?', None) -> False."""
    m = re.fullmatch(r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d{1,2}):(\d{2})", (resets or "").strip())
    if not m:
        return False
    base = datetime.fromtimestamp(ts).replace(second=0, microsecond=0)
    days = ("Mon Tue Wed Thu Fri Sat Sun".split().index(m.group(1)) - base.weekday()) % 7
    t = (base + timedelta(days=days)).replace(hour=int(m.group(2)), minute=int(m.group(3)))
    if t < base:
        t += timedelta(days=7)
    return now >= t.timestamp() + 60  # reset shown truncated to the minute: wait for the minute to end


def quota(now=None):
    """bgjobs cache -> {label: {pct, resets[, reset]}, age_min[, stale]}; None if missing or unreadable.
    A window whose reset time has passed since the cache was written gets pct: null, reset: true."""
    now = time.time() if now is None else now
    try:
        with open(QUOTA_CACHE) as h:
            c = json.load(h)
        ts, out = c.get("ts", 0), {}
        for pct, text in c.get("out") or []:
            label = text.split("[")[0].strip() or "?"
            rs = re.search(r"resets\s+(.+?)(?:\s{2,}|\s*\(|$)", text)
            rs = rs.group(1).strip() if rs else None
            out[label] = {"pct": None, "resets": rs, "reset": True} if _reset_passed(rs, ts, now) else {"pct": pct, "resets": rs}
        out["age_min"] = round((now - ts) / 60)
        if out["age_min"] > QUOTA_STALE_MIN:
            out["stale"] = True
        return out
    except (OSError, ValueError, TypeError, AttributeError):
        return None


# ---- inferred --------------------------------------------------------------------------------------------------

def _under(p, claim):
    claim = os.path.normpath(os.path.expanduser(claim))
    return p == claim or p.startswith(claim.rstrip("/") + "/") or (not claim.startswith("/") and ("/" + claim) in p)


def overlaps(ss, declared):
    out = []
    for i, a in enumerate(ss):
        for b in ss[i + 1:]:
            ca, cb = (declared.get(s["sid"], {}).get("claims") or [] for s in (a, b))
            on = sorted(set(a["edited"]) & set(b["edited"]))
            on += [p for p in b["edited"] if any(_under(p, c) for c in ca)] + [p for p in a["edited"] if any(_under(p, c) for c in cb)]
            on += [c for c in ca for d in cb if _under(c, d) or _under(d, c)]
            if on:
                out.append({"issue": "overlap", "a": a["name"], "b": b["name"], "on": sorted(set(on))[:3], "method": "overlap.paths.v1"})
    return out[:OVERLAP_MAX]


def _worker(f, x, mt, results, now):
    """Facts of one subagent shared by agents, session and node (one source of truth): full id, parent result, state, duration_s, last."""
    aid = os.path.basename(f)[6:-6]
    r = results.get(aid, {})
    state = "working" if _active(x, mt, now) else "done" if r.get("status") not in (None, "async_launched", "running") or \
        x["last_event"] == ("assistant", "end_turn") else "idle"
    dur = r.get("totalDurationMs")  # parent-measured; else in-transcript work span (later notifications don't count)
    dur_s = round(dur / 1000) if dur is not None else _secs(x["first_ts"], x["work_ts"] or x["last_ts"])
    return aid, r, state, dur_s, _iso(x["work_ts"] or mt)


def _node_row(f, st, mt, results, now):
    full, res, state, dur_s, last = _worker(f, st, mt, results, now)
    aid, meta, tok = full[:ID_CHARS], _meta(f), _tokens(st)
    last_text = st["turns"][-1]["text_len"] if st["turns"] else 0
    status = "running" if _active(st, mt, now) else res.get("status") if res.get("status") not in (None, "async_launched") else (
        "done" if st["last_event"] == ("assistant", "end_turn") else "stopped")
    return {"node": aid, "type": meta.get("agentType") or res.get("agentType"), "desc": (meta.get("description") or res.get("description") or "")[:EXCERPT_CHARS],
            "model": res.get("resolvedModel") or (_models(st) or [meta.get("model")])[-1], "tok": tok,
            "returned": res.get("returned", last_text), "dur_s": dur_s, "status": status, "state": state,
            "outcome": outcome(full, st, res, state), "last": last}


def low_return(ss, now, cut):
    out = []
    for s in ss:
        for f, st, mt in s["subs"]:
            if mt < cut:
                continue
            r = _node_row(f, st, mt, s["res"], now)
            burned_k = (r["tok"]["in"] + r["tok"]["cw"] + r["tok"]["out"]) / 1000
            if r["status"] != "running" and burned_k >= LOW_RETURN_MIN_BURN_K and r["returned"] / burned_k < LOW_RETURN_CHARS_PER_K \
                    and not delivered_code(f, st, s["res"].get(os.path.basename(f)[6:-6], {})):
                out.append({"issue": "low_return", "session": s["name"], "node": r["node"], "burned_k": round(burned_k),
                            "returned_chars": r["returned"], "method": "burn_ratio.v1"})
    return out


def delivered_code(f, x, r):
    """Worker whose output is a commit (final text cites a hash, or its worktree is merged / ahead): code, not chars."""
    text = r.get("result") or (x["turns"][-1]["text"] if x["turns"] else "")
    if COMMIT_RE.search(text):
        return True
    wt = worktree(x, False, _meta(f), text)
    return bool(wt and (wt["merged"] or wt["ahead"] > 0))


def sub_lines(s, now, cut):
    """Subagents written in the window, newest first: 'desc | model | ctx | cost | min | last tool | status'."""
    out = []
    for f, st, mt in sorted((x for x in s["subs"] if x[2] >= cut), key=lambda x: -x[2]):
        r = _node_row(f, st, mt, s["res"], now)
        out.append(f"{r['desc'][:40] or r['node'][:8]} | {(r['model'] or '?').replace('claude-', '')} | ctx {round(st['last_ctx'] / 1000)}k | "
                   f"${_cost(st):.2f} | {round((r['dur_s'] or 0) / 60)}m | {st['last_tool'] or '-'} | {r['status']}")
    return out[:SUB_LINES] + ([f"+{len(out) - SUB_LINES} more (session tool)"] if len(out) > SUB_LINES else [])


def _ledger():
    return os.path.join(data_dir(load_config()), "delegations.jsonl")


def ledger_tail():
    try:
        with open(_ledger(), "rb") as h:
            h.seek(max(0, os.path.getsize(_ledger()) - 8192))
            lines = h.read().decode(errors="replace").splitlines()[-LEDGER_LINES:]
    except OSError:
        return []
    out = []
    for l in lines:
        try:
            d = json.loads(l)
        except ValueError:
            continue
        qb, qa = (d.get(k) or {} for k in ("quota_before", "quota_after"))
        out.append(f"{d.get('ts')} {d.get('item')} {d.get('agent') or d.get('desc') or '?'} {d.get('topology') or '-'} "
                   f"7d {qb.get('7d')}->{qa.get('7d')} tok {d.get('tokens')} tests {d.get('tests_pass')} accepted {d.get('accepted')}")
    return out


# ---- tools -----------------------------------------------------------------------------------------------------

def overview(a):
    window_h = a.get("window_h", DEFAULT_WINDOW_H)
    now = time.time()
    cut = now - window_h * 3600
    # a live process idle since before the window is not "live now" (working / waiting_user still shown)
    ss = [s for s in all_sessions(window_h) if s["last"] >= cut or s["state"] in ("working", "waiting_user")]
    declared = _load("declared.json")
    me = caller_id(a)
    rows = []
    for s in ss:
        dec = declared.get(s["sid"])
        r = {"name": s["name"], "sid": s["sid"][:8], "state": s["state"], "cost": round(s["cost"], 2), "ctx_k": round(s["ctx"] / 1000),
             "last": _iso(s["last"]), "touching": s["touching"], "subagents": sub_lines(s, now, now - window_h * 3600),
             "goal": (dec["goal"] if dec else s["scan"]["goal"] or "")[:GOAL_CHARS], "goal_src": "declared" if dec else "inferred"}
        if s["partial"]:
            r["partial"] = True
        if s["sid"] == me:
            r["self"] = True
        rows.append(r)
    cursors = _load("cursors.json")
    prev = (cursors.get(me) or {}) if me else {}
    snap = {s["sid"]: {"name": r["name"], "state": r["state"], "cost": r["cost"], "touching": r["touching"]} for s, r in zip(ss, rows)}
    delta, changed = [], set()
    if prev and not a.get("full"):
        old = prev.get("snap", {})
        for sid, n in snap.items():
            o, parts = old.get(sid), []
            if not o:
                parts.append(f"new ({n['state']})")
            else:
                if o["state"] != n["state"]:
                    parts.append(f"{o['state']} -> {n['state']}")
                if n["cost"] - o["cost"] >= DELTA_MIN_COST:
                    parts.append(f"+${n['cost'] - o['cost']:.2f}")
                new_dirs = [d for d in n["touching"] if d not in o["touching"]]
                if new_dirs:
                    parts.append("touching " + ", ".join(new_dirs))
            if parts:
                delta.append(f"{n['name']}: " + ", ".join(parts))
                changed.add(sid[:8])
        delta += [f"{o['name']}: left window" for sid, o in old.items() if sid not in snap]
    if me:
        cursors[me] = {"ts": now, "snap": snap}
        _save("cursors.json", cursors)
    full = not prev or a.get("full")
    shown = rows if full else [r for r in rows if r["sid"] in changed]
    out = {"since": _iso(prev["ts"]) if prev and not a.get("full") else None, "window_h": window_h, "caller": me,
           "delta": delta if not full else None, "quota": quota(),
           "measured": {"agg": "agg.v1", "sessions": shown, "unchanged": len(rows) - len(shown)},
           "inferred": overlaps(ss, declared) + low_return(ss, now, now - window_h * 3600), "ledger": ledger_tail()}
    if not me:
        out["note"] = "no caller id (CLAUDE_CODE_SESSION_ID unset, no caller argument): full view, no delta"
    return out


def session(a):
    s = find_session(a.get("id_or_name"))
    st, now = s["scan"], time.time()
    dec = _load("declared.json").get(s["sid"])
    turns = []
    lim = a.get("limit")
    for i in range(max(0, len(st["turns"]) - (lim or RECENT_TURNS)), len(st["turns"])):
        t = st["turns"][i]
        tok = _tokens(st, i)
        turns.append({"node": f"t{i + 1}", "ts": _iso(t["ts"]), "prompt": t["prompt"], "tools": dict(t["tools"].most_common(3)),
                      "out_k": round(tok["out"] / 1000, 1), "returned": t["text_len"]})
    files = {}
    for x in [st] + [x for _, x, _ in s["subs"]]:
        for k, (kind, ts, n) in x["touch"].items():
            if not k.startswith("port:") and (k not in files or ts > files[k][1]):
                files[k] = (kind if k not in files or files[k][0] != "edit" else "edit", ts)
    cwd = st["cwd"] or ""
    flist = sorted(files.items(), key=lambda kv: (kv[1][0] == "edit", kv[1][1] or ""), reverse=True)  # edits first, newest first
    nodes = sorted(({**{k: v for k, v in _node_row(f, x, mt, s["res"], now).items() if k != "tok"}, "cost": round(_cost(x), 2)}
                    for f, x, mt in s["subs"]), key=lambda r: r["last"] or "", reverse=True)  # tok: see node
    main_tok = _tokens(st)
    return {"name": s["name"], "sid": s["sid"], "state": s["state"], "cwd": cwd, "started": _iso(st["first_ts"]), "last": _iso(s["last"]),
            "goal": {"text": dec["goal"] if dec else st["goal"], "src": "declared" if dec else "inferred",
                     "method": None if dec else "goal.first_prompt.v1", "claims": dec["claims"] if dec else None},
            "measured": {"agg": "agg.v1", "cost": round(s["cost"], 2), "cost_main": round(_cost(st), 2), "tok_main": main_tok,
                         "ctx_k": round(s["ctx"] / 1000), "turns_total": len(st["turns"]), "partial": s["partial"],
                         "turns": turns, "files": [{"path": os.path.relpath(k, cwd) if cwd and k.startswith(cwd + "/") else k, "kind": v[0],
                                                     "last": _iso(v[1]) if v[1] else None} for k, v in flist[:lim or SESSION_FILES]],
                         "files_total": len(files), "nodes": nodes[:lim or SESSION_NODES], "nodes_total": len(nodes)}}


def _secs(a, b):
    if not (a and b):
        return None
    return round((datetime.fromisoformat(b.replace("Z", "+00:00")) - datetime.fromisoformat(a.replace("Z", "+00:00"))).total_seconds())


def _agent_row(aid, parent, desc, model, state, x, last, dur_s=None):
    return {"id": aid, "parent": parent, "desc": " ".join((desc or "").split("\n")[0].split())[:DESC_CHARS],
            "model": (model or "?").replace("claude-", ""), "state": state, "cost": round(_cost(x), 3),
            "ctx_k": round(x["last_ctx"] / 1000), "peak_ctx_k": round(x["peak_ctx"] / 1000), "turns": len(x["msgs"]),
            "tool_calls": sum(x["tools"].values()), "started": _iso(x["first_ts"]), "last": last if isinstance(last, str) else _iso(last), "duration_s": dur_s if dur_s is not None else _secs(x["first_ts"], x["work_ts"] or x["last_ts"])}


def _git(path, *args):
    r = subprocess.run(["git", "-C", path, *args], capture_output=True, text=True, timeout=GIT_TIMEOUT_S)
    return r.returncode, r.stdout


def _gitdirs(path):
    """(worktree git dir, common git dir) of a linked worktree from its .git file."""
    with open(os.path.join(path, ".git")) as h:
        gd = os.path.join(path, h.read().split("gitdir:", 1)[1].strip())
    return gd, os.path.normpath(os.path.join(gd, "..", ".."))


def _read(f):
    try:
        with open(f) as h:
            return h.read()
    except OSError:
        return ""


def _wt_sig(path):
    """mtimes of the files git rewrites on commit/checkout/merge/add in this worktree and its main repo; None if unreadable."""
    try:
        gd, cd = _gitdirs(path)
        fs = [os.path.join(gd, n) for n in ("HEAD", "index", os.path.join("logs", "HEAD"))]
        fs += [os.path.join(cd, n) for n in (os.path.join("logs", "HEAD"), "packed-refs", os.path.join("refs", "heads"))]
        return tuple(os.stat(f).st_mtime_ns if os.path.exists(f) else 0 for f in fs)
    except (OSError, IndexError):
        return None


def _wt_facts(path, live=True):
    """{path, branch, ahead, dirty, merged} of one linked worktree vs the main worktree's HEAD; None on any failure.
    merged = ahead 0 (tip is an ancestor of main) and the tip moved since the branch was created (oldest reflog entry).
    Cache: WT_CACHE_S for a running worker; a finished one's facts are reused while _wt_sig is unchanged (git calls dominate agents).
    Two git subprocesses per miss (rev-list, status): HEADs and the branch reflog are read from the git dirs directly."""
    hit, now = _WT.get(path), time.time()
    if hit and (now - hit[0] < WT_CACHE_S or (not live and now - hit[0] < WT_DONE_CACHE_S and hit[2] is not None and hit[2] == _wt_sig(path))):
        return hit[1]
    try:
        gd, cd = _gitdirs(path)
        ref = lambda h: h[16:] if h.startswith("ref: refs/heads/") else h or None  # HEAD file -> branch name, else detached sha
        main, br = ref(_read(os.path.join(cd, "HEAD")).strip()), ref(_read(os.path.join(gd, "HEAD")).strip())
        rc3, ahead = _git(path, "rev-list", "--count", f"{main}..HEAD")
        rc4, st = _git(path, "status", "--porcelain")
        if not main or not br or rc3 or rc4:
            raise ValueError
        br = br if _read(os.path.join(gd, "HEAD")).startswith("ref:") else "HEAD"
        ahead, merged = int(ahead), False
        if ahead == 0 and br != "HEAD":
            log = _read(os.path.join(cd, "logs", "refs", "heads", br)).split("\n")
            log = [l.split() for l in log if l.strip()]
            merged = bool(log) and len(log[0]) > 1 and log[0][1] != log[-1][1]  # creation sha vs current tip
        v = {"path": path, "branch": br, "ahead": ahead, "dirty": len(st.splitlines()), "merged": merged}
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        v = None
    _WT[path] = (time.time(), v, _wt_sig(path))  # sig after git ran: status may refresh the index
    return v


def worktree(x, live=True, meta=None, text=""):
    """Linked git worktree (root holds a .git file) of a worker: the harness's meta worktreePath (isolation: worktree), else the first
    absolute path in its first prompt inside one, else its transcript cwd. Paths that no longer exist give None (finished worker:
    _wt_from_hash)."""
    for p in [(meta or {}).get("worktreePath")] + (x.get("paths") or []) + [x.get("cwd")]:
        if not p:
            continue
        p, prev = os.path.normpath(p), None
        while p != prev and p not in ("/", "//"):
            if os.path.isfile(os.path.join(p, ".git")):
                return _wt_facts(p, live)
            if os.path.isdir(os.path.join(p, ".git")):
                break  # main checkout, not a worktree
            p, prev = os.path.dirname(p), p
    return None if live else _wt_from_hash(x, text)


COMMIT_RE = re.compile(r"\bcommit(?:ted|s)?\W{1,3}(?:\w+\W{1,3}){0,2}?((?=[a-f]*\d)[0-9a-f]{7,40})\b", re.I)
BRANCH_RE = re.compile(r"\bwt/[\w.-]*\w")


def _wt_from_hash(x, text):
    """Finished worker whose worktree is gone: last commit hash quoted in its final text ("commit 3319669") vs the HEAD of the repo
    holding its paths/cwd -> {path None, branch (wt/* named in the text), ahead, dirty 0, merged = ahead 0}; None if no hash or unknown."""
    hs = COMMIT_RE.findall(text or "")
    if not hs:
        return None
    for p in (x.get("paths") or []) + [x.get("cwd")]:
        p = os.path.normpath(p or "/")
        while not os.path.isdir(p):
            p = os.path.dirname(p)
        root = _git_root(p)
        if root:
            break
    else:
        return None
    k = (root, hs[-1])
    hit = _WT.get(k)
    if hit and time.time() - hit[0] < WT_DONE_CACHE_S and hit[2] == _wt_sig_main(root):
        return hit[1]
    try:
        rc, ahead = _git(root, "rev-list", "--count", f"HEAD..{hs[-1]}")
        b = BRANCH_RE.findall(text)
        v = None if rc else {"path": None, "branch": b[0] if b else None, "ahead": int(ahead), "dirty": 0, "merged": int(ahead) == 0}
    except (OSError, ValueError, subprocess.SubprocessError):
        v = None
    _WT[k] = (time.time(), v, _wt_sig_main(root))
    return v


def _wt_sig_main(root):
    """mtimes of a main checkout's HEAD log and refs: a merge into main changes them."""
    fs = [os.path.join(root, ".git", n) for n in (os.path.join("logs", "HEAD"), "packed-refs", os.path.join("refs", "heads"))]
    return tuple(os.stat(f).st_mtime_ns if os.path.exists(f) else 0 for f in fs)


def _result(x, r, state):
    """Worker's final text (result its parent received, else last assistant text), collapsed; None while running."""
    if state == "working":
        return None
    t = " ".join(MD_RE.sub(" ", r.get("result") or (x["turns"][-1]["text"] if x["turns"] else "")).split())
    return _cut(t, AGENT_RESULT_CHARS) or None


def _cut(t, n):
    """t in at most n chars, cut at the last space (unless it is in the first half) with "…" appended."""
    if len(t) <= n:
        return t
    c = t[:n - 1]
    sp = c.rfind(" ")
    return (c[:sp] if sp > n // 2 else c).rstrip(" ,;:") + "…"


MD_RE = re.compile(r"\*\*|__|`+|^\s*(?:[-*]|#+|\d+\.)\s+", re.M)  # markdown marks dropped from result excerpts
PARTIAL_RE = re.compile(r"context (?:hard )?limit|hard limit|out of context|ran out|stopped (?:before|early)|before committing|"
                        r"not (?:yet )?committed|nothing (?:is |was )?committed|(?:isn't|is not|wasn't|not) (?:yet )?(?:finished|started|done)\b|soft limit|(?:did not|didn't|could not|couldn't) (?:commit|finish)|no commit hash|partly done|unfinished|incomplete|left undone", re.I)
FAIL_RE = re.compile(r"\b(?:error|failed|failing|could not|couldn't|unable to|blocked|cannot)\b", re.I)
OK_RE = re.compile(r"\bcommitted\b|\ball (?:\d+ )?(?:tests? )?pass|\btests? pass|\bpassed\b|\bgreen\b", re.I)
HASH_RE = re.compile(r"\b[0-9a-f]{7,40}\b")
HANDOFF_RE = re.compile(r"/[\w./-]*/handoffs/[\w.-]+\.md")
_OUTCOME = {}   # (agent id, final text hash) -> outcome
_D1 = [True]    # d1 still usable in this process


def _d1_outcome(goal, text):
    if not _D1[0]:
        return None
    body = {"state": f"Worker task: {goal or '?'}\nWorker final report: {text}", "q": "How did this worker end its task?", "type": "choice",
            "opts": [["ok", "finished the task: committed or tests pass"], ["partial", "stopped early: context limit, not committed, work left"],
                     ["failed", "could not do the task: errors or blocked"]]}
    try:
        req = urllib.request.Request(D1_URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=D1_TIMEOUT_S) as h:
            ans = json.load(h)["answer"]
        return ans["choice"] if ans.get("confidence", 0) >= D1_MIN_P and ans["choice"] in ("ok", "partial", "failed") else None
    except Exception:
        _D1[0] = False
        return None


def outcome(aid, x, r, state):
    """ok | partial | failed for a finished worker from its final text (keywords, d1 when ambiguous); None while running."""
    if state == "working":
        return None
    text = (x["turns"][-1]["text"] if x["turns"] else "") or r.get("result") or ""
    text = " ".join(MD_RE.sub(" ", text).split())[:OUTCOME_TEXT_CHARS]
    k = (aid, hash(text))
    if k not in _OUTCOME:
        hashed = bool(HASH_RE.search(text)) and "commit" in text.lower()
        ok, bad = bool(OK_RE.search(text)) or hashed, bool(FAIL_RE.search(text))
        no_commit = x.get("asks_commit") and not hashed and "committed" not in text.lower()
        if not text or PARTIAL_RE.search(text):
            v = "partial"
        elif hashed or ok != bad:  # a commit hash outweighs failure words (often quoted: "failed" shown as "error")
            v = "partial" if ok and no_commit else "ok" if ok else "failed"
        else:
            v = _d1_outcome(x["goal"], text) or ("partial" if no_commit else "ok")
        _OUTCOME[k] = v
    return _OUTCOME[k]


def handoff(aid, x, r):
    """Existing handoff file named in a finished worker's final text, else HANDOFF_DIR/<agent id>.md if present; None otherwise."""
    for t in ((x["turns"][-1]["text"] if x["turns"] else ""), r.get("result") or ""):
        for p in HANDOFF_RE.findall(t):
            if os.path.isfile(p):
                return p
    p = os.path.join(HANDOFF_DIR, aid + ".md")
    return p if os.path.isfile(p) else None


def next_step(w, later):
    """merge | resume | inspect | None for a worker row; later = (paths, wt paths) of workers started after it (a reuse supersedes it)."""
    wt, o = w.get("wt"), w.get("outcome")
    if w["state"] == "working" or (wt and wt["merged"]):
        return None
    if (wt and wt["path"] in later[1]) or (w.get("handoff") and w["handoff"] in later[0]):
        return None
    if wt and wt["ahead"] > 0:
        return "merge" if o == "ok" and not wt["dirty"] else "inspect"
    if o == "partial":
        return "resume" if w.get("handoff") else "inspect"
    return "inspect" if o == "failed" else None


def stale_action(w, later, turns, now):
    """True when an inspect/resume next step is old (ACTION_STALE_H) and the orchestrator moved on: a user turn started after the
    worker finished, or a later worker was merged. later = worker rows started after it; turns = turn start times (ISO)."""
    fin = _since_ts(w.get("last"))
    if w.get("next") not in ("inspect", "resume") or fin is None or now - fin < ACTION_STALE_H * 3600:
        return False
    return any((_since_ts(t) or 0) > fin for t in turns) or any(v["wt"] and v["wt"]["merged"] for v in later)


def agents(a):
    """Delegation tree of one session (agents.v1): main agent, then subagents by start, with per-agent cost from transcripts."""
    key = a.get("session") or caller_id(a)
    if not key:
        raise ToolError("no session: pass session or set CLAUDE_CODE_SESSION_ID")
    s = find_session(key)
    st, now = s["scan"], time.time()
    cut = now - a["window_h"] * 3600 if "window_h" in a else 0
    res = s["res"]
    last_model = lambda x: list(x["msgs"].values())[-1][1] if x["msgs"] else None
    dec = _load("declared.json").get(s["sid"])
    main_id = s["sid"][:ID_CHARS]
    main = _agent_row(main_id, None, dec["goal"] if dec else st["goal"], last_model(st),
                      {"working": "working", "dead": "done"}.get(s["state"], "idle"), st, os.path.getmtime(s["path"]))
    workers = []
    for f, x, mt in s["subs"]:
        if mt < cut:
            continue
        aid, r, state, dur_s, last = _worker(f, x, mt, res, now)
        meta = _meta(f)
        workers.append(_agent_row(aid[:ID_CHARS], (meta.get("parentAgentId") or "")[:ID_CHARS] or main_id,
                                  meta.get("description") or r.get("description") or x["goal"], r.get("resolvedModel") or last_model(x) or meta.get("model"),
                                  state, x, last, dur_s))
        workers[-1].update(result=_result(x, r, state), outcome=outcome(aid, x, r, state), wt=(x, state == "working", meta, r.get("result") or (x["turns"][-1]["text"] if x["turns"] else "")))
        hp = state != "working" and handoff(aid, x, r)
        if hp:
            workers[-1]["handoff"] = hp
        workers[-1]["_paths"] = x["paths"]
    with ThreadPoolExecutor(GIT_THREADS) as ex:  # git subprocesses release the GIL
        for w, v in zip(workers, list(ex.map(lambda w: worktree(*w["wt"]), workers))):
            w["wt"] = v
    workers.sort(key=lambda w: w["started"] or "")
    nexts = {}
    for i, w in enumerate(workers):  # paths/worktrees of later workers: a resumed or redone worker needs nothing
        n = next_step(w, ({p for v in workers[i + 1:] for p in v["_paths"]}, {v["wt"]["path"] for v in workers[i + 1:] if v["wt"]}))
        if n:
            w["next"] = n
            if stale_action(w, workers[i + 1:], [t["ts"] for t in st["turns"] if t["prompt"] and t["ts"]], now):
                del w["next"]
                w["stale"] = n  # kept visible, not counted: the orchestrator already moved on
            else:
                nexts[n] = nexts.get(n, 0) + 1
    for w in workers:
        del w["_paths"]
    wc = sorted(w["ctx_k"] for w in workers)
    wcost = sum(_cost(x) for _, x, mt in s["subs"] if mt >= cut)
    if "since" in a:
        return agents_delta(a, s, workers, nexts, now)
    lim = a.get("limit", AGENTS_ROWS)
    omitted = 0
    if not a.get("all"):  # main + running + newest finished; the dashboard passes all=true
        done = sorted((w for w in workers if w["state"] != "working"), key=lambda w: w["last"] or "")
        keep = {id(w) for w in workers if w["state"] == "working"} | {id(w) for w in done[-AGENTS_RECENT_DONE:]}
        shown = [w for w in workers if id(w) in keep]
        omitted = len(workers) - len(shown)
    else:
        shown = workers
    if a.get("all") and "limit" not in a:  # all = every worker, same set as session nodes (the dashboard joins them by id)
        lim = len(shown)
    out = {"session": {"name": s["name"], "sid": main_id, "state": s["state"]},
           "totals": {"cost": round(_cost(st) + wcost, 2), "orch_cost": round(_cost(st), 2), "workers_cost": round(wcost, 2),
                      "workers": len(workers), "running": sum(w["state"] == "working" for w in workers),
                      "partial": sum(w["outcome"] == "partial" for w in workers),
                      "next": nexts, "stale": sum("stale" in w for w in workers),
                      "to_merge": sum(bool(w["wt"] and w["wt"]["ahead"] > 0 and not w["wt"]["merged"]) for w in workers),
                      "median_ctx_k": (wc[len(wc) // 2] if len(wc) % 2 else (wc[len(wc) // 2 - 1] + wc[len(wc) // 2]) / 2) if wc else None},
           "agents": [main] + shown[-lim:], "omitted": omitted}
    if len(shown) > lim:
        out["over_limit"] = len(shown) - lim
    return out


def _since_ts(since):
    """cursor (epoch seconds) or ISO time -> epoch; '' / unparseable -> None (first heartbeat)."""
    if not since:
        return None
    if since.isdigit():
        return int(since)
    try:
        d = datetime.fromisoformat(since.replace("Z", "+00:00"))
        return (d if d.tzinfo else d.astimezone()).timestamp()
    except ValueError:
        return None


def quota_line(q):
    """quota() -> 'quota 5h 19% 7d 38%' (+ 'reset' per passed window, 'stale Nm'); 'quota ?' if no cache."""
    if not q:
        return "quota ?"
    parts = [f"{k} reset" if v.get("reset") else f"{k} {v['pct']:g}%" for k, v in q.items() if isinstance(v, dict)]
    return "quota " + " ".join(parts) + (f" stale {q['age_min']}m" if q.get("stale") else "")


def agents_delta(a, s, workers, nexts, now):
    """Heartbeat view: workers whose state/outcome/next changed since the cursor, a new cursor and a one-line summary
    (running, next counts, quota). Unknown cursor or ISO time with no snapshot -> workers active since then (basis: activity);
    empty since -> running + workers with a next step (basis: actionable)."""
    sig = {w["id"]: [w["state"], w.get("outcome"), w.get("next")] for w in workers}
    store = _load("agents_cursors.json")
    snaps = store.get(s["sid"], {})
    t = _since_ts(a["since"])
    base = max((int(c) for c in snaps if t is not None and int(c) <= t), default=None)
    if base is not None:
        old, basis = snaps[str(base)], "cursor"
        changed = [w for w in workers if old.get(w["id"]) != sig[w["id"]]]
    elif t is not None:
        old, basis = {}, "activity"
        changed = [w for w in workers if (_since_ts(w["last"]) or 0) >= t - 60 or w["state"] == "working"]
    else:
        old, basis = {}, "actionable"
        changed = [w for w in workers if w["state"] == "working" or w.get("next")]
    cursor = str(int(now))
    snaps[cursor] = sig
    store[s["sid"]] = {c: snaps[c] for c in sorted(snaps, key=int)[-AGENTS_CURSORS_KEEP:]}
    _save("agents_cursors.json", store)
    running = sum(w["state"] == "working" for w in workers)
    summary = ", ".join([f"{running} running"] + [f"{n} {k}" for k, n in sorted(nexts.items())] + [quota_line(quota(now))])
    rows = []
    for w in changed:
        r = {"id": w["id"], "desc": w["desc"], "state": w["state"]}
        for k in ("outcome", "next"):
            if w.get(k):
                r[k] = w[k]
        if w.get("next") == "resume":
            r["handoff"] = w.get("handoff")
        if w.get("wt") and w.get("next"):
            r["branch"] = w["wt"].get("branch")
        if old.get(w["id"]) and old[w["id"]][0] != w["state"]:
            r["was"] = old[w["id"]][0]
        rows.append(r)
    return {"cursor": cursor, "basis": basis, "summary": summary, "changed": rows, "unchanged": len(workers) - len(rows)}


def node(a):
    s = find_session(a.get("session"))
    key, st, now = (a.get("node") or "").strip(), s["scan"], time.time()
    if re.fullmatch(r"t\d+", key):
        i = int(key[1:]) - 1
        if not 0 <= i < len(st["turns"]):
            raise ToolError(f"{s['name']} has turns t1..t{len(st['turns'])}")
        t = st["turns"][i]
        dur = None
        if t["ts"] and t["end"]:
            dur = round((datetime.fromisoformat(t["end"].replace("Z", "+00:00")) - datetime.fromisoformat(t["ts"].replace("Z", "+00:00"))).total_seconds())
        return {"session": s["name"], "node": key, "kind": "turn", "ts": _iso(t["ts"]), "prompt": t["prompt"], "prompt_chars": t["chars"],
                "model": _models(st, i), "tok": _tokens(st, i), "dur_s": dur, "tools": dict(t["tools"]), "returned": t["text_len"],
                "excerpt": t["text"][:RESULT_EXCERPT_CHARS]}
    for f, x, mt in s["subs"]:
        if os.path.basename(f)[6:-6].startswith(key) and key:
            r = _node_row(f, x, mt, s["res"], now)
            res = s["res"].get(os.path.basename(f)[6:-6], {})
            excerpt = res.get("result") or (x["turns"][-1]["text"] if x["turns"] else "")
            return {"session": s["name"], "kind": "subagent", **r, "models": _models(x), "tools": dict(x["tools"]),
                    "turns": len(x["turns"]), "excerpt": excerpt[:RESULT_EXCERPT_CHARS]}
    raise ToolError(f"no node {key!r} in {s['name']}: use t<N> for turns or a subagent id from session")


def _listeners(port):
    """pids listening on a TCP port (own processes only: /proc fd links of others are unreadable)."""
    inodes = set()
    for f in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(f) as h:
                for l in list(h)[1:]:
                    p = l.split()
                    if p[3] == "0A" and int(p[1].rsplit(":", 1)[1], 16) == port:
                        inodes.add(p[9])
        except (OSError, IndexError, ValueError):
            pass
    pids = []
    if inodes:
        for fd in glob.glob("/proc/[0-9]*/fd/*"):
            try:
                link = os.readlink(fd)
            except OSError:
                continue
            if link.startswith("socket:[") and link[8:-1] in inodes:
                pids.append(int(fd.split("/")[2]))
    return sorted(set(pids))


def _ppid(pid):
    try:
        with open(f"/proc/{pid}/stat") as h:
            return int(h.read().rsplit(")", 1)[1].split()[1])
    except (OSError, ValueError, IndexError):
        return 0


def who_touches(a):
    path, port = a.get("path"), a.get("port")
    if bool(path) == (port is not None):
        raise ArgError("give exactly one of path or port")
    ss = all_sessions(a.get("window_h", LOOKUP_WINDOW_H))
    rows, bound = [], []
    if port is not None:
        pids = {r["pid"]: sid for sid, r in registry().items()}
        names = {s["sid"]: s["name"] for s in ss}
        for pid in _listeners(port):
            p, owner = pid, None
            while p > 1 and owner is None:
                owner = pids.get(p)
                p = _ppid(p)
            try:
                cmd = open(f"/proc/{pid}/cmdline").read().replace("\0", " ").strip()[:EXCERPT_CHARS]
            except OSError:
                cmd = None
            bound.append({"pid": pid, "cmd": cmd, "session": names.get(owner, owner[:8] if owner else None), "method": "port.v1"})
    for s in ss:
        for node_id, x in [("main", s["scan"])] + [(os.path.basename(f)[6:-6][:ID_CHARS], x) for f, x, _ in s["subs"]]:
            hits = [(k, v) for k, v in x["touch"].items()
                    if (port is not None and k == f"port:{port}") or (path and not k.startswith("port:") and _under(k, path))]
            if hits:
                kinds = sorted({v[0] for _, v in hits})
                rows.append({"session": s["name"], "sid": s["sid"][:8], "node": node_id, "kind": kinds, "n": sum(v[2] for _, v in hits),
                             "last": _iso(max(v[1] or "" for _, v in hits) or None), "state": s["state"]})
    rows.sort(key=lambda r: r["last"] or "", reverse=True)
    declared = [{"session": next((s["name"] for s in ss if s["sid"] == sid), sid[:8]), "claim": c}
                for sid, d in _load("declared.json").items() for c in d.get("claims") or []
                if (path and (_under(os.path.normpath(os.path.expanduser(path)), c) or _under(c, path))) or (port is not None and c == f"port:{port}")]
    return {"target": path or f"port:{port}", "bound": bound if port is not None else None, "touched": rows[:WHO_ROWS],
            "total": len(rows), "declared": declared, "method": "port.v1" if port is not None else "edit/read from Edit/Write/Read/Grep/Glob tool inputs"}


def declare(a):
    me = caller_id(a)
    if not me:
        raise ToolError("no caller id: set CLAUDE_CODE_SESSION_ID or pass caller")
    d = _load("declared.json")
    d[me] = {"goal": a.get("goal", "")[:SESSION_GOAL_CHARS], "claims": a.get("claims") or [], "ts": time.time()}
    _save("declared.json", d)
    ss = all_sessions(DEFAULT_WINDOW_H)
    mine = [o for o in overlaps(ss, d) if me[:8] in (o["a"], o["b"]) or any(s["sid"] == me and s["name"] in (o["a"], o["b"]) for s in ss)]
    return {"caller": me, "declared": d[me], "overlaps": mine}


def record(a):
    """Delegation ledger: phase=start stores quota_before under <data dir>/live/; phase=end appends the full line."""
    if a["phase"] not in ("start", "end"):
        raise ArgError("phase must be start or end")
    q = {k: v["pct"] for k, v in (quota() or {}).items() if isinstance(v, dict)} or None
    pending = _load("pending.json")
    if a["phase"] == "start":
        pending[a["item"]] = {"ts": _iso(time.time()), "quota_before": q, **{k: a[k] for k in ("agent", "desc", "topology") if k in a}}
        _save("pending.json", pending)
        return {"started": a["item"], "quota_before": q}
    p = pending.pop(a["item"], {})
    line = {"ts": p.get("ts") or _iso(time.time()), "agent": a.get("agent", p.get("agent")), "desc": a.get("desc", p.get("desc")),
            "item": a["item"], "topology": a.get("topology", p.get("topology")), "quota_before": p.get("quota_before"), "quota_after": q,
            **{k: a.get(k) for k in ("tokens", "commit", "tests_pass", "accepted")}}
    with open(_ledger(), "a") as h:
        h.write(json.dumps(line) + "\n")
    _save("pending.json", pending)
    return line


def method(a):
    if a.get("id"):
        if a["id"] not in METHODS_DOC:
            raise ToolError(f"unknown method {a['id']!r}; known {sorted(METHODS_DOC)}")
        return {"id": a["id"], "doc": METHODS_DOC[a["id"]]}
    return METHODS_DOC


# ---- call log and mcp_status -----------------------------------------------------------------------------------

_STARTED = time.time()


def _stale():
    """One line if live.py on disk is newer than this process (it still runs the old code), else None."""
    try:
        m = os.path.getmtime(__file__)
    except OSError:
        return None
    hm = lambda t: time.strftime("%H:%M", time.localtime(t))
    return (f"live.py changed at {hm(m)} after this server started at {hm(_STARTED)}; restart the MCP to get new tools/args"
            if m > _STARTED else None)
_VERSION = []


def _ts_iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log_call(rec):
    """Append one line to live/calls.jsonl; trims to the newest CALLS_MAX_LINES//2 past CALLS_MAX_LINES. Never raises."""
    try:
        p = _state_file("calls.jsonl")
        with open(p, "a") as h:
            h.write(json.dumps(rec, separators=(",", ":")) + "\n")
        if os.path.getsize(p) > CALLS_MAX_LINES * 120:  # cheap pre-check (lines are ~150 bytes) before counting
            with open(p) as h:
                lines = h.readlines()
            if len(lines) > CALLS_MAX_LINES:
                with open(p + ".tmp", "w") as h:
                    h.writelines(lines[-(CALLS_MAX_LINES // 2):])
                os.replace(p + ".tmp", p)
    except Exception:
        pass


def _calls():
    try:
        with open(_state_file("calls.jsonl")) as h:
            lines = h.readlines()
    except OSError:
        return []
    out = []
    for l in lines:
        try:
            r = json.loads(l)
        except ValueError:
            continue
        if isinstance(r, dict) and isinstance(r.get("tool"), str) and isinstance(r.get("ts"), str):
            out.append(r)
    return out


def _version():
    if not _VERSION:
        try:
            v = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5)
            _VERSION.append(v.stdout.strip() if v.returncode == 0 and v.stdout.strip() else None)
        except (OSError, subprocess.SubprocessError):
            _VERSION.append(None)
    return _VERSION[0]


def _pct(xs, q):
    return int(xs[int(round(q * (len(xs) - 1)))]) if xs else 0


def _mcp_uses(path, cut_iso):
    """[(tool_use id, tool, ts)] of this server's tools in one transcript since cut_iso (tail MAX_SCAN_BYTES only)."""
    out = []
    try:
        with open(path, "rb") as h:
            size = os.fstat(h.fileno()).st_size
            h.seek(max(0, size - MAX_SCAN_BYTES))
            data = h.read()
    except OSError:
        return out
    for raw in data.split(b"\n"):
        if MCP_PREFIX.encode() not in raw:
            continue
        try:
            d = json.loads(raw)
            ts = d.get("timestamp") or ""
            if d.get("type") != "assistant" or ts[:19] < cut_iso[:19]:
                continue
            for c in d["message"]["content"]:
                if isinstance(c, dict) and c.get("type") == "tool_use" and str(c.get("name", "")).startswith(MCP_PREFIX):
                    out.append((c.get("id"), c["name"][len(MCP_PREFIX):], ts[:19] + "Z"))
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return out


def orchestrators(hours):
    """Claude Code sessions (main + subagent transcripts) that called otm-live tools in the window, newest first."""
    cut = time.time() - hours * 3600
    cut_iso, reg, by = _ts_iso(cut), registry(), {}
    files = [(os.path.basename(p)[:-6], p, True) for p in glob.glob(os.path.join(PROJECTS_DIR, "*", "*.jsonl"))]
    files += [(p.split(os.sep)[-3], p, False) for p in glob.glob(os.path.join(PROJECTS_DIR, "*", "*", "subagents", "agent-*.jsonl"))]
    mains = {sid: p for sid, p, m in files if m}
    for sid, p, _ in files:
        try:
            if os.path.getmtime(p) < cut:
                continue
        except OSError:
            continue
        o = by.setdefault(sid, {"seen": set(), "tools": Counter(), "last": ""})
        for uid, tool, ts in _mcp_uses(p, cut_iso):
            if uid in o["seen"]:
                continue
            o["seen"].add(uid)
            o["tools"][tool] += 1
            o["last"] = max(o["last"], ts)
    rows = []
    for sid, o in by.items():
        if not o["tools"]:
            continue
        name = (reg.get(sid) or {}).get("name")
        if not name and sid in mains:
            t = scan(mains[sid])["titles"]
            name = t.get("custom-title") or t.get("agent-name") or t.get("ai-title")
        rows.append({"sid": sid[:ID_CHARS], "name": name or sid[:ID_CHARS], "calls": sum(o["tools"].values()),
                     "tools": dict(o["tools"].most_common()), "last": o["last"]})
    return sorted(rows, key=lambda r: r["last"], reverse=True)[:STATUS_ORCH]


def mcp_status(a):
    """Is otm-live working, who calls it, how heavy are the answers: calls.jsonl stats + transcript callers in the window."""
    hours = a.get("hours", 24)
    cut_iso = _ts_iso(time.time() - hours * 3600)
    calls = [r for r in _calls() if r["ts"] >= cut_iso]
    tools = []
    for n in FUNCS:
        rs = [r for r in calls if r["tool"] == n]
        ms = sorted(int(r.get("ms") or 0) for r in rs)
        ch = [int(r.get("chars") or 0) for r in rs]
        tools.append({"name": n, "calls": len(rs), "errors": sum(not r.get("ok", True) for r in rs), "p50_ms": _pct(ms, .5),
                      "p95_ms": _pct(ms, .95), "avg_chars": round(sum(ch) / len(ch)) if ch else 0, "max_chars": max(ch, default=0),
                      "last": max((r["ts"] for r in rs), default=None)})
    tools.sort(key=lambda t: -t["calls"])
    v = a.get("verbose")
    out = {"server": {"name": SERVER_INFO["name"], "pid": os.getpid(), "started": _ts_iso(_STARTED), "version": _version(),
                       "log": _state_file("calls.jsonl"), "stale": bool(_stale())},
            "window_h": hours, "calls": len(calls), "errors": sum(not r.get("ok", True) for r in calls), "tools": tools,
            "orchestrators": orchestrators(hours),
            "recent": [{"ts": r["ts"], "tool": r["tool"], "via": r.get("via"), "ms": r.get("ms"), "chars": r.get("chars"),
                        "ok": r.get("ok", True), **({"args": r.get("args", "")} if v else {})}
                       for r in calls[-(STATUS_RECENT if v else STATUS_RECENT_COMPACT):][::-1]]}
    if _stale():
        out["stale"] = _stale()
    if not v:
        out["unused"] = [t["name"] for t in tools if not t["calls"]]
        out["tools"] = [t for t in tools if t["calls"]]
    return out


# ---- protocol --------------------------------------------------------------------------------------------------

S, I = {"type": "string"}, {"type": "integer", "minimum": 1}
CALLER = {"caller": {"type": "string", "description": "caller session id when CLAUDE_CODE_SESSION_ID is not set"}}
TOOLS = [
    ("overview", "Live/recent agent sessions on this machine, one line each (state, cost, ctx, touching), quota left, "
     "overlaps and low-return subagents. Returns only sessions changed since this caller's last call unless full.",
     {"full": {"type": "boolean"}, "window_h": I, **CALLER}),
    ("session", "One session by name or id prefix: goal, state, recent turns, files touched, subagents with tokens and returned size.",
     {"id_or_name": S, "limit": I}),
    ("agents", "Delegation tree of one session (default: the caller's): main agent + each subagent with parent, desc, model, state, "
     "cost, ctx_k, peak_ctx_k, turns, tool_calls, started/last/duration; workers also result (final text excerpt), outcome "
     "(ok|partial|failed, null while running) and wt (git worktree from meta, prompt or cwd: branch, ahead, dirty, merged; worktree gone: path null, from the commit "
     "hash in the result); totals orchestrator vs workers cost, running, partial, to_merge, median ctx; omitted = finished workers "
     "left out (all=true lists them); over_limit = rows beyond limit dropped. "
     "since= switches to the compact heartbeat view {cursor, basis, summary, changed, unchanged}.",
     {"session": S, "window_h": I, "limit": I,
      "since": {"type": "string", "description": "heartbeat delta: the cursor from the previous call (or an ISO time; '' on the first beat). "
                "Returns only workers whose state/outcome/next changed + a one-line summary with quota; pass back the new cursor"}, "all": {"type": "boolean", "description": "every worker, not trimmed to the response budget (large; for the dashboard); default main + running + "
                                                       f"{AGENTS_RECENT_DONE} newest finished, rest counted in omitted"}, **CALLER}),
    ("node", "One subagent (id prefix from session) or turn (t<N>): model, tokens, duration, tools, returned size, result excerpt.",
     {"session": S, "node": S}),
    ("who_touches", "Sessions/subagents that edited or read a path, or mentioned/listen on a port, with last ts.",
     {"path": S, "port": {"type": "integer", "minimum": 1}, "window_h": I}),
    ("declare", "Publish this caller's one-line goal and the paths/ports (port:N) it intends to touch; flags overlaps.",
     {"goal": S, "claims": {"type": "array", "items": S}, **CALLER}),
    ("method", "What an inferred metric id computes (state.v1, overlap.paths.v1, burn_ratio.v1 ...); no id lists all.",
     {"id": S}),
    ("record", "Delegation ledger: phase=start before delegating (captures quota), phase=end after (appends one line to delegations.jsonl).",
     {"phase": S, "item": S, "agent": S, "desc": S, "topology": S, "tokens": {"type": "integer", "minimum": 0}, "commit": S,
      "tests_pass": {"type": "boolean"}, "accepted": {"type": "boolean"}}),
    ("mcp_status", "Health of this otm-live server: pid/start/version, per-tool calls, errors, p50/p95 ms, answer chars (from live/calls.jsonl), "
     "Claude Code sessions calling it (transcripts) and the newest calls, over the last hours (default 24). "
     f"Default compact: tools with 0 calls only in unused, {STATUS_RECENT_COMPACT} recent calls without args.",
     {"hours": I, "verbose": {"type": "boolean", "description": f"every tool, {STATUS_RECENT} recent calls with args"}}),
]
REQUIRED = {"session": ["id_or_name"], "node": ["session", "node"], "declare": ["goal"], "record": ["phase", "item"]}
TOOL_LIST = [{"name": n, "description": d, "inputSchema": {"type": "object", "properties": p, "additionalProperties": False,
                                                           **({"required": REQUIRED[n]} if n in REQUIRED else {})}}
             for n, d, p in TOOLS]
TOOL_ARGS = {n: p for n, _, p in TOOLS}
FUNCS = {"overview": overview, "session": session, "agents": agents, "node": node, "who_touches": who_touches, "declare": declare, "method": method, "record": record, "mcp_status": mcp_status}


def check_args(name, args):
    if not isinstance(args, dict):
        raise ArgError("arguments must be an object")
    unknown = [k for k in args if k not in TOOL_ARGS[name]]
    allowed = ", ".join(f"{k} ({p['type']})" for k, p in TOOL_ARGS[name].items())
    for k in REQUIRED.get(name, []):
        if k not in args:
            hint = f"; got {unknown[0]!r}: pass {{{json.dumps(k)}: {json.dumps(args[unknown[0]])}}} instead" if len(unknown) == 1 else ""
            raise ArgError(f"{name}: missing argument {k!r}{hint}; allowed: {allowed}")
    if unknown:
        near = difflib.get_close_matches(unknown[0], list(TOOL_ARGS[name]), 1, 0.6)
        hint = f"; did you mean {near[0]!r}? pass {{{json.dumps(near[0])}: {json.dumps(args[unknown[0]])}}}" if near else ""
        raise ArgError(f"{name}: unknown argument {unknown[0]!r}{hint}; allowed: {allowed} (server started {_ts_iso(_STARTED)}; "
                       "if your schema lists it, this server process predates it and needs a restart)" + (f"; {_stale()}" if _stale() else ""))
    for k, v in args.items():
        spec = TOOL_ARGS[name][k]
        typ = spec["type"]
        if typ == "string" and not isinstance(v, str):
            raise ArgError(f"{k} must be a string")
        if typ == "boolean" and not isinstance(v, bool):
            raise ArgError(f"{k} must be a JSON boolean: pass {{{json.dumps(k)}: true}} or false, not {json.dumps(v)}")
        if typ == "integer" and (not isinstance(v, int) or isinstance(v, bool) or v < spec["minimum"]):
            raise ArgError(f"{k} must be an integer >= {spec['minimum']}, e.g. {{{json.dumps(k)}: {max(spec['minimum'], 1)}}}")
        if typ == "array" and not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
            raise ArgError(f"{k} must be a list of strings")


def fit(data):
    """Trim any result to MAX_RESPONSE_TOKENS: pop the tail of the longest nested list, recorded in truncated {path: full length}."""
    trunc = {}
    while size_tokens({**data, "truncated": trunc} if trunc and isinstance(data, dict) else data) > MAX_RESPONSE_TOKENS:
        lists = []

        def walk(o, path):
            if isinstance(o, dict):
                for k, v in o.items():
                    walk(v, f"{path}.{k}" if path else k)
            elif isinstance(o, list):
                if len(o) > 1:
                    lists.append((len(json.dumps(o)), path, o))
                for i, v in enumerate(o):
                    walk(v, f"{path}[{i}]")
        walk(data, "")
        if not lists:
            break
        _, path, lst = max(lists, key=lambda x: x[0])
        trunc.setdefault(path, len(lst))
        lst.pop()
    if trunc and isinstance(data, dict):
        data["truncated"] = trunc
    return data


def call_tool(name, args, via="api"):
    """Shared by MCP (via="mcp") and HTTP /api (default "api"): (is_error, data or message); logs to calls.jsonl unless via is None.
    Raises ArgError for bad arguments."""
    t0, rec = time.time(), {"ts": _ts_iso(time.time()), "tool": str(name)[:60]}
    try:
        rec["args"] = json.dumps(args, separators=(",", ":"), default=str)[:CALLS_ARGS_CHARS]
    except (TypeError, ValueError, RecursionError):
        rec["args"] = "?"
    try:
        is_err, data = _call_tool(name, args)
    except Exception as e:
        rec.update(ms=round((time.time() - t0) * 1000), chars=0, ok=False, via=via, err=f"{type(e).__name__}: {e}"[:200])
        if via:
            log_call(rec)
        raise
    rec.update(ms=round((time.time() - t0) * 1000), chars=len(data) if is_err else len(json.dumps(data)), ok=not is_err, via=via)
    if is_err:
        rec["err"] = str(data)[:200]
    if via:
        log_call(rec)
    return is_err, data


def _call_tool(name, args):
    if name not in FUNCS:
        raise ArgError(f"unknown tool: {name}")
    check_args(name, args)
    try:
        data = FUNCS[name](args)
        return False, data if args.get("all") is True else fit(data)  # all=true: caller asked for every row (dashboard); fit would drop the newest
    except (ToolError, OSError, ValueError, KeyError) as e:
        return True, str(e)


def _initialize(params):
    want = params.get("protocolVersion")
    return {"protocolVersion": want if want in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0], "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO}


METHODS = {"initialize": _initialize, "ping": lambda params: {}, "tools/list": lambda params: {"tools": TOOL_LIST}}


def handle(msg):
    mid, meth, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if "id" not in msg:
        return None
    if msg.get("jsonrpc") != "2.0" or not isinstance(meth, str):
        return _err(mid, -32600, "invalid request: needs jsonrpc 2.0 and a method")
    if not isinstance(params, dict):
        return _err(mid, -32602, "params must be an object")
    if meth in METHODS:
        return _ok(mid, METHODS[meth](params))
    if meth != "tools/call":
        return _err(mid, -32601, f"method not found: {meth}")
    try:
        is_err, data = call_tool(params.get("name"), params.get("arguments", {}), via="mcp")
    except ArgError as e:
        return _err(mid, -32602, str(e))
    return _ok(mid, {"content": [{"type": "text", "text": data if is_err else json.dumps(data)}], "isError": is_err})


def serve(inp=sys.stdin, out=sys.stdout):
    for line in inp:
        if not line.strip():
            continue
        msg = None
        try:
            msg = json.loads(line)
            resp = handle(msg) if isinstance(msg, dict) else _err(None, -32600, "invalid request")
        except (json.JSONDecodeError, RecursionError):
            resp = _err(None, -32700, "parse error")
        except Exception as e:  # never die on one request
            resp = None if not isinstance(msg, dict) or "id" not in msg else _err(msg["id"], -32603, f"internal error: {type(e).__name__}")
        if resp is not None:
            out.write(json.dumps(resp) + "\n")
            out.flush()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--call", help="run one tool and print its JSON result, e.g. --call overview")
    ap.add_argument("--args", default="{}", help="JSON arguments for --call")
    a = ap.parse_args()
    if a.call:
        print(json.dumps(call_tool(a.call, json.loads(a.args), via=None)[1], indent=1))
    else:
        serve()


if __name__ == "__main__":
    main()
