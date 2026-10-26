#!/usr/bin/env python3
"""Orchestrator UX from Claude Code main transcripts: per human turn, reply length, tools, how the human reacted next.
Specs: METHOD.md (U-*).

python3 04-auto-analysis/orch-ux/orch_ux.py [--days N] [--root DIR] [--config PATH] [--out DIR] [--no-d1]
Reads <project>/<session>.jsonl (main threads only; subagents/ files are skipped), in memory;
writes orch_ux.json (overall, calibration, nudges, sessions, last turns). The pipeline copies a compact section to readout.json.
"""
import argparse, glob, json, os, re, sys, time, urllib.request
from datetime import datetime, timedelta, timezone

import pathlib  # numbered stage dirs aren't importable: find the repo, put 02-measure/ on sys.path
REPO = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir())
sys.path.insert(0, str(REPO / "02-measure"))
from schemas.config import load_config, data_dir

DAYS = 7
ROOT = "~/.claude/projects"
HARNESS = "claude-code"
OUT = "orch_ux.json"
AGENT_TOOLS = ("Agent", "Task")            # U-turn: tool uses that launch a subagent
INTERRUPT = "[Request interrupted by user"  # U-next: interrupt marker in a user message
REJECT = ("The user doesn't want to proceed", "tool use was rejected")  # U-next: in a tool_result
SKIP_PREFIX = ("<", "This session is being continued", "Caveat:", "/")  # U-human: not a real human message
AUTO_PREFIX = ("Autonudge heartbeat", "Resumed by another session")  # U-human: cron/heartbeat and cross-session resume prompts, automated even when not isMeta
SYNTHETIC = "<synthetic>"                   # U-turn: message.model of harness-made assistant text ("No response requested."), not a reply
PASTE = "<pasted_content"                  # U-human: a human paste starts with this tag; it is a human message
PASTE_RX = r"<pasted_content[^>]*>.*?(</pasted_content[^>]*>|$)"  # U-classify: pasted text is not the human's reaction
HUMAN_ORIGINS = (None, "human")            # U-human: origin.kind of a typed prompt (task-notification, peer -> automated)
AUTO_ENTRYPOINTS = ("sdk-cli",)            # U-human: `claude -p` / SDK runs are scripted, not a human
TURN_END = "turn_duration"                 # U-turn: system line closing the response to a prompt
# U-classify: keyword heuristics, lowercased substring match (regexes where marked); first list that matches wins
VISIBLE_THEME = ["sigo sin", "sigue sin", "no veo", "no se ve", "no aparece", "no funciona", "no anda", "todavía no",
                 "still don't see", "still not", "still no", "doesn't work", "not working", "i don't see", "inconsistent"]
VISIBLE_RX = [r"\brot[oa]s?\b", r"\bbroken\b", r"\ba veces no\b", r"\bno (est[aá] )?lleg"]  # "ta roto", "no está llegando"
LENGTH_THEME = ["muy largo", "más corto", "mas corto", "demasiado largo", "resumí", "resumi ", "más breve", "mas breve", "más corta", "mas corta", "too long",
                "shorter", "tl;dr", "tldr", "menos texto"]
CORRECTION = VISIBLE_THEME + LENGTH_THEME + [
    "equivoc", "por qué", "por que ", "porqué", "no era", "no es eso", "no te pedí", "no te pedi",
    "te dije", "ya te dije", "otra vez", "de nuevo", "wrong", "why did", "why are", "i said", "i told you", "not what",
    "me refiero", "me refería", "me referia", "i mean", "nunca más", "nunca mas", "never again", "missing",
    "estás seguro", "estas seguro", "está seguro", "esta seguro", "are you sure", "no se entiende", "no me dice nada"]
CORRECTION_RX = [r"^no\b", r"^nope\b", r"\bmal\b", r"\bno hagas\b", r"\bdon'?t\b", r"^faltan?\b", r"\bse fue\b",
                 # train-set gaps (dev + holdout), 2026-10-25: redirecting openers, "still", "useless", frustration
                 r"^(est[aá] bien|s[ií]|ok|dale),? pero\b", r"^pero\b", r"^digo\b", r"\ba lo que voy\b", r"^sin\s",
                 r"\bsigue con\b", r"\bno sirve\b", r"\bno entiendo\b", r"\brespet[aá]", r"\bte fuiste\b",
                 r"\bboludo\b", r"\bla puta\b", r"\bme cago\b", r"\bcarajo\b",
                 r"\bqu ?[eé] ?pas[oó]\b", r"\bwhat happened\b"]  # "queda quota, qué pasó": the outcome surprised the human
MORE = ["más detalle", "mas detalle", "explicá", "explica", "explicame", "detallá", "ampliá", "elaborá", "contame más",
        "contame mas", "más info", "more detail", "explain", "elaborate", "expand", "tell me more", "go deeper"]
MORE_RX = [r"^y\s.{1,60}\?$", r"^(and|what about)\s.{1,60}\?$", r"^y(\s+\S+){1,3}$", r"\bpor ejemplo\b", r"^¿?y si\b.*\?"]
SHORT_Q_WORDS = 6                          # a question of at most this many words, with no other cue -> more
NEXT_KINDS = ("correction", "more", "neutral")
D1_URL = "http://localhost:6975/ask"       # U-d1: local decision model, optional
D1_TIMEOUT = 2.0                           # seconds per call; the first failure turns d1 off for the run
D1_MAX_CALLS = 500
D1_MORE_CONF = 0.65                        # U-eval: d1 may only flip heuristic neutral -> more, at this confidence or above
EVAL = "tests/data/classify_eval.jsonl"    # U-eval: hand-labelled follow-up prompts, relative to this dir
HOLDOUT = "tests/data/classify_holdout.jsonl"  # U-eval: labelled blind, used to tune rules since 2026-10-25 (now training)
TEST2 = "tests/data/classify_test2.jsonl"  # U-eval: fresh prompts labelled blind before any run; never used to tune
D1_Q = "How does the human react to the AI agent's previous answer?"
D1_OPTS = [["correction", "complains something is wrong, missing, not visible, not working, or the answer is too long"],
           ["more", "asks for more detail or explanation of the previous answer"],
           ["neutral", "acknowledges, or gives a new instruction or request"]]
# U-calib: target reply length. The target is derived (p50 of replies the human let pass, capped by "too long" complaints);
TARGET_PRIOR_WORDS = 120                   # only this prior is a guess (~6 sentences of ~20 words); data outweighs it past PRIOR_N turns
PRIOR_N = 10                               # the prior weighs like this many neutral turns
TOLERANCE = 0.25                           # verdict ok within target * (1 +- TOLERANCE)
MIN_REPLY_WORDS = 15                       # target never below this
# U-nudge thresholds
LONG_REPLY_SHARE = 0.3                     # share of replies over target * (1 + TOLERANCE) -> long_replies
VISIBLE_REPEAT_MIN = 2                     # "sigo sin ver"-style corrections in the window -> verify_visible
LENGTH_COMPLAINTS_MIN = 1                  # "muy largo"-style corrections -> length_complaints
LONG_CHAIN_TOOLS = 15                      # an interrupt/reject after this many tool calls in the turn -> long_chain
LONG_CHAIN_MIN = 2
ASK_BACK_SHARE = 0.25                      # replies ending in a question -> ask_back
ASK_BACK_MIN = 3
MORE_SHARE = 0.15                          # turns followed by "more" -> too_short
TOP_SESSIONS = 20
LAST_TURNS = 40
SNIPPET = 80
NUDGE_CHARS = 140
ISO = "%Y-%m-%dT%H:%M:%SZ"
FENCE_RX = r"```.*?(```|$)"                # U-overall: fenced code block (an unclosed fence runs to the end)
# U-workers: worker (subagent) -> orchestrator reports
NOTIF = "<task-notification"               # async worker result, a user message in the main thread
ASYNC_ACK = ("Async agent launched", "async_launched")  # Agent tool_result that is only the launch ack
PARTIAL_RX = r"context limit|out of context|\bpartly\b|\bpartial(ly)?\b|\bincomplete\b|stopped before"
CTX_LIMIT_RX = r"context limit|out of context"
COMMIT_RX = r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b"
TESTS_RX = (r"\b\d+\s+(passed|failed)\b|\b(tests?|suite)\b[^\n]{0,60}\b(green|ok|pass(ed|es|ing)?|fail(ed|s|ing)?|pasan?)\b"
            r"|\bpasan?\b[^\n]{0,30}\btests?\b|\bpytest\b")  # "suite passes (75 tests)", "57 tests OK", "pasan los tests"
BUDGET_RX = r"(?:≤|<=|<|under|max|budget)\s*~?\s*(\d+)\s*k\b"  # "Stay under ~60k context", "≤60k context"
ASK_COMMIT_RX = r"\bcommit\b"        # the prompt asked for a commit -> report should state the hash
ASK_TESTS_RX = r"\btests?\b"             # the prompt mentions tests -> report should state the result
FOLLOWUP_MANY = 3                          # orchestrator tool calls after a report before replying -> "needed follow-up"
PARTIAL_RATE_MAX = 0.2                     # nudge workers_partial above this share
OVER_BUDGET_RATE_MAX = 0.2                 # nudge workers_over_budget above this share (of workers with a stated budget)
GAPS_RATE_MAX = 0.3                        # nudge workers_report_gaps above this share (of reports whose prompt asked)
FOLLOWUP_P50_MAX = 2                       # nudge workers_followup when follow-up calls p50 exceeds this
WORKER_MIN = 3                             # no worker nudges below this many finished workers
WORKER_EXAMPLES = 3


def ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (AttributeError, ValueError):
        return None


def iso(d):
    return d.strftime(ISO) if d else None


def pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else None


def words(s):
    return len(s.split())


def reply_words(s):
    """U-overall: words of the final reply the human reads, fenced code blocks excluded (commands/code aren't prose length)."""
    return words(re.sub(FENCE_RX, " ", s, flags=re.S))


def code_words(s):
    """U-overall: words inside fenced code blocks of the reply, reported apart from prose."""
    return sum(words(m.group(0).strip("`")) for m in re.finditer(FENCE_RX, s, flags=re.S))


def snip(s):
    s = " ".join(s.split())
    return s if len(s) <= SNIPPET else s[:SNIPPET - 1] + "…"


def blocks(d):
    c = (d.get("message") or {}).get("content")
    return [{"type": "text", "text": c}] if isinstance(c, str) else [b for b in c or [] if isinstance(b, dict)]


def human_text(d):
    """U-human: the text of a real human message, else None."""
    if d.get("type") != "user" or d.get("isMeta") or d.get("isCompactSummary") or d.get("isSidechain"):
        return None
    if d.get("entrypoint") in AUTO_ENTRYPOINTS or (d.get("origin") or {}).get("kind") not in HUMAN_ORIGINS:
        return None
    bs = blocks(d)
    if any(b.get("type") == "tool_result" for b in bs):
        return None
    t = "\n".join(b.get("text", "") for b in bs if b.get("type") == "text").strip()
    if not t or (t.startswith(SKIP_PREFIX) and not t.startswith(PASTE)) or t.startswith(AUTO_PREFIX) or INTERRUPT in t:
        return None
    return t


def has(t, lst, rxs=()):
    return any(k in t for k in lst) or any(re.search(r, t) for r in rxs)


def heuristic(text):
    """U-classify: correction | more | neutral, and the theme ("visible", "length" or None)."""
    t = re.sub(PASTE_RX, " ", text, flags=re.S).lower().strip()
    if has(t, VISIBLE_THEME, VISIBLE_RX):
        return "correction", "visible"
    if has(t, LENGTH_THEME):
        return "correction", "length"
    if has(t, CORRECTION, CORRECTION_RX):
        return "correction", None
    if has(t, MORE, MORE_RX) or (t.endswith("?") and len(t.split()) <= SHORT_Q_WORDS):
        return "more", None
    return "neutral", None


class D1:
    """U-d1: optional refinement by the local decision model; off after the first failure or slow call."""
    def __init__(self, on=True):
        self.on, self.calls, self.used = on, 0, 0

    def raw(self, prev_reply, text):
        """d1's answer {choice, confidence}, or None (off / error)."""
        if not self.on or self.calls >= D1_MAX_CALLS:
            return None
        self.calls += 1
        body = {"state": f"Agent answer (start): {snip(prev_reply)}\nHuman reply: {text[:400]}", "q": D1_Q,
                "type": "choice", "opts": D1_OPTS}
        try:
            req = urllib.request.Request(D1_URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=D1_TIMEOUT) as r:
                a = json.load(r)["answer"]
            if a.get("choice") not in NEXT_KINDS:
                raise ValueError(a)
        except Exception:
            self.on = False
            return None
        return a

    def ask(self, prev_reply, text, kind=None):
        """U-d1: "more" when the heuristic said neutral and d1 says more with >= D1_MORE_CONF, else None."""
        if kind != "neutral":
            return None
        a = self.raw(prev_reply, text)
        if not a or a["choice"] != "more" or a.get("confidence", 0) < D1_MORE_CONF:
            return None
        self.used += 1
        return "more"


def classify(text, prev_reply="", d1=None):
    kind, theme = heuristic(text)
    if theme or d1 is None:  # explicit theme keywords win over the model
        return kind, theme
    k = d1.ask(prev_reply, text, kind)
    return (k or kind), None


def evaluate(rows, d1=None):
    """U-eval: accuracy of heuristic, raw d1 and the combined classifier on labelled rows {text, prev, label}."""
    res = {k: {"n": 0, "baseline": 0, "heuristic": 0, "d1": 0, "combined": 0} for k in NEXT_KINDS}
    for r in rows:
        c, y = res[r["label"]], r["label"]
        a = d1.raw(r["prev"], r["text"]) if d1 else None
        c["n"] += 1
        c["baseline"] += y == "neutral"  # always-neutral
        c["heuristic"] += heuristic(r["text"])[0] == y
        c["d1"] += bool(a) and a["choice"] == y
        c["combined"] += classify(r["text"], r["prev"], d1)[0] == y
    tot = {m: sum(c[m] for c in res.values()) for m in ("n", "baseline", "heuristic", "d1", "combined")}
    return {"per_class": res, "total": tot, "d1_up": bool(d1 and d1.on)}


def parse(lines, sid="", since=None, d1=None):
    """U-turn: transcript lines (dicts) -> (turns, session name). One turn per real human message."""
    turns, cur, name, titles = [], None, None, {}
    def close(nxt=None, theme=None):
        if cur:
            if cur["next"] is None:
                cur["next"], cur["theme"] = nxt, theme
            turns.append(cur)
    for d in lines:
        t = d.get("type")
        if t in ("custom-title", "agent-name", "ai-title"):
            titles[t] = d.get("customTitle") or d.get("agentName") or d.get("aiTitle")
            continue
        if d.get("isSidechain"):
            continue
        when = ts(d.get("timestamp"))
        h = human_text(d)
        if h is not None:
            if cur and not cur["tool_calls"] and not cur["_reply"] and cur["next"] is None:
                # U-turn: queued prompt (typed while the agent was busy, no reply in between) -> same turn, not a reaction
                cur["user_words"] += words(h)
                cur["user_text"] = snip(cur["user_text"] + " " + h)
                continue
            if cur:
                close(*classify(h, cur["_reply"], d1))
            if name is None:
                name = snip(h)[:40]
            cur = {"ts": when, "sid": sid, "user_words": words(h), "reply_words": 0, "tool_calls": 0, "subagents": 0,
                   "min": 0.0, "next": None, "theme": None, "asks": False, "user_text": snip(h), "_reply": "", "_end": when,
                   "code_words": 0, "_done": False}
            continue
        if cur is None or cur["_done"]:
            continue  # U-turn: after the response to the human ends, heartbeat/notification responses aren't this turn
        if t == "system" and d.get("subtype") == TURN_END or (
                t == "user" and text_of(d).strip() and INTERRUPT not in text_of(d)
                and not any(b.get("type") == "tool_result" for b in blocks(d))):
            cur["_done"] = True  # turn_duration, or an automated user message (notification, heartbeat, reminder)
            continue
        if when:
            cur["_end"] = when
        if t == "user":
            for b in blocks(d):
                s = json.dumps(b.get("content", "")) if b.get("type") == "tool_result" else b.get("text", "")
                if b.get("type") == "tool_result" and any(r in s for r in REJECT) and cur["next"] is None:
                    cur["next"] = "reject"
                elif b.get("type") == "text" and INTERRUPT in s and cur["next"] is None:
                    cur["next"] = "interrupt"
        elif t == "assistant":
            for b in blocks(d):
                if b.get("type") == "tool_use":
                    cur["tool_calls"] += 1
                    cur["subagents"] += b.get("name") in AGENT_TOOLS
                    cur["_reply"] = ""
                elif b.get("type") == "text" and b.get("text", "").strip() and (d.get("message") or {}).get("model") != SYNTHETIC:
                    cur["_reply"] = (cur["_reply"] + "\n" + b["text"]).strip()
        if t == "assistant" or t == "user":
            cur["reply_words"] = reply_words(cur["_reply"])
            cur["code_words"] = code_words(cur["_reply"])
            cur["asks"] = cur["_reply"].rstrip().rstrip("*_`").endswith("?")
    close()
    for c in turns:
        c["min"] = round((c["_end"] - c["ts"]).total_seconds() / 60, 1) if c["ts"] and c["_end"] else 0.0
        c["reply_text"] = snip(c.pop("_reply"))
        c.pop("_end"), c.pop("_done")
    if since:
        turns = [c for c in turns if c["ts"] and c["ts"] >= since]
    return turns, titles.get("custom-title") or titles.get("agent-name") or titles.get("ai-title") or name or ""


def read_lines(path, tail_bytes=None):
    with open(path, "rb") as f:
        if tail_bytes:
            f.seek(max(0, os.path.getsize(path) - tail_bytes))
            if f.tell():
                f.readline()  # partial line
        for raw in f:
            try:
                yield json.loads(raw)
            except ValueError:
                continue


def text_of(d):
    return "\n".join(b.get("text", "") for b in blocks(d) if b.get("type") == "text")


def tag(s, name):
    m = re.search(rf"<{name}>(.*?)</{name}>", s, re.S)
    return m.group(1).strip() if m else ""


def peak_ctx(path):
    """Largest input context (input + cache read + cache write) over the worker's assistant messages."""
    peak = 0
    try:
        for raw in open(path, "rb"):
            if b'"usage"' not in raw or b'"assistant"' not in raw:
                continue
            try:
                u = json.loads(raw)["message"]["usage"]
            except (ValueError, KeyError, TypeError):
                continue
            peak = max(peak, sum(u.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")))
    except OSError:
        pass
    return peak or None


def grade(report, prompt, status="completed"):
    """U-workers: what a final report states. Used by the stage and the hook."""
    budget = re.search(BUDGET_RX, prompt or "", re.I)
    return {"report_words": words(report), "report_chars": len(report),
            "partial": status not in ("completed", "") or bool(re.search(PARTIAL_RX, report, re.I)),
            "ctx_limit": bool(re.search(CTX_LIMIT_RX, report, re.I)), "commit": bool(re.search(COMMIT_RX, report)), "tests": bool(re.search(TESTS_RX, report, re.I)),
            "asked_commit": bool(re.search(ASK_COMMIT_RX, prompt or "", re.I)),
            "asked_tests": bool(re.search(ASK_TESTS_RX, prompt or "", re.I)),
            "budget": int(budget.group(1)) * 1000 if budget else None}


def workers_of(lines, sid, sub_dir, since=None):
    """U-workers: finished workers of one main transcript (task-notifications and sync Agent results), last result per agent."""
    prompts, out = {}, {}
    for i, d in enumerate(lines):
        if d.get("isSidechain"):
            continue
        rep = None
        if d.get("type") == "assistant":
            for b in blocks(d):
                if b.get("type") == "tool_use" and b.get("name") in AGENT_TOOLS:
                    inp = b.get("input") or {}
                    prompts[b.get("id")] = (inp.get("prompt") or "", inp.get("description") or "")
        elif d.get("type") == "user":
            t = text_of(d)
            if NOTIF in t:
                u = tag(t, "usage")
                st = re.search(r"subagent_tokens>(\d+)", u)
                rep = (tag(t, "task-id"), tag(t, "tool-use-id"), tag(t, "status"), tag(t, "result"), int(st.group(1)) if st else None)
            for b in blocks(d):
                if b.get("type") == "tool_result" and b.get("tool_use_id") in prompts:
                    c = b.get("content")
                    s = c if isinstance(c, str) else "\n".join(x.get("text", "") for x in c or [] if isinstance(x, dict))
                    if any(a in s for a in ASYNC_ACK):
                        continue
                    aid = re.search(r"agentId: (\w+)", s)
                    st = re.search(r"subagent_tokens: (\d+)", s)
                    rep = (aid.group(1) if aid else b["tool_use_id"], b["tool_use_id"], "completed",
                           re.split(r"\nagentId: ", s)[0].strip(), int(st.group(1)) if st else None)
        if not rep:
            continue
        when = ts(d.get("timestamp"))
        if since and (not when or when < since):
            continue
        aid, tuid, status, report, sub_tokens = rep
        follow = 0  # orchestrator tool calls before its next text reply
        for e in lines[i + 1:]:
            if e.get("isSidechain"):
                continue
            if e.get("type") == "user" and (human_text(e) is not None or NOTIF in text_of(e)):
                break
            if e.get("type") == "assistant":
                bs = blocks(e)
                if any(b.get("type") == "text" and b.get("text", "").strip() for b in bs):
                    break
                follow += sum(b.get("type") == "tool_use" for b in bs)
        prompt, desc = prompts.get(tuid, ("", ""))
        peak = peak_ctx(os.path.join(sub_dir, f"agent-{aid}.jsonl")) or sub_tokens
        w = dict(grade(report, prompt, status), sid=sid, agent=aid, desc=desc[:60], ts=iso(when), status=status,
                 peak_ctx=peak, followup_calls=follow)
        w["over_budget"] = bool(w["budget"] and peak and peak > w["budget"])
        w["gaps"] = [k for k in ("commit", "tests") if w["asked_" + k] and not w[k]]
        out[aid] = w
    return list(out.values())


def summarize_workers(ws):
    """U-workers: the `workers` section of orch_ux.json."""
    n = len(ws)
    rate = lambda xs, f: round(sum(map(f, xs)) / len(xs), 2) if xs else None
    budgeted = [w for w in ws if w["budget"]]
    asked = [w for w in ws if w["asked_commit"] or w["asked_tests"]]
    def why(w):
        r = (["hit context limit" if w["ctx_limit"] else ("partial" if w['status'] == 'completed' else w['status'])] if w["partial"] else [])
        if w["over_budget"]:
            r.append(f"peak ctx {w['peak_ctx'] // 1000}k > budget {w['budget'] // 1000}k")
        if w["gaps"]:
            r.append("no " + "/".join(w["gaps"]) + " in report")
        if w["followup_calls"] >= FOLLOWUP_MANY:
            r.append(f"{w['followup_calls']} follow-up calls")
        return r
    score = lambda w: 2 * w["partial"] + w["over_budget"] + bool(w["gaps"]) + (w["followup_calls"] >= FOLLOWUP_MANY)
    worst = sorted((w for w in ws if score(w)), key=lambda w: (score(w), w["followup_calls"]), reverse=True)
    return {"n": n, "report_words_p50": pct([w["report_words"] for w in ws], .5) or 0,
            "partial_rate": rate(ws, lambda w: w["partial"]), "over_budget_rate": rate(budgeted, lambda w: w["over_budget"]),
            "with_budget": len(budgeted), "gaps_rate": rate(asked, lambda w: bool(w["gaps"])),
            "followup_calls_p50": pct([w["followup_calls"] for w in ws], .5) or 0,
            "peak_ctx_p50": pct([w["peak_ctx"] for w in ws if w["peak_ctx"]], .5),
            "examples": [{"sid": w["sid"], "agent": w["agent"], "desc": w["desc"], "why": "; ".join(why(w))}
                         for w in worst[:WORKER_EXAMPLES]]}


def worker_nudges(ws, sm):
    """U-workers nudges: thresholds at the top."""
    out, n = [], sm["n"]
    if n < WORKER_MIN:
        return out
    pa = sum(w["partial"] for w in ws)
    if sm["partial_rate"] > PARTIAL_RATE_MAX:
        out.append(nudge("workers_partial", "Workers end partial / at the context limit: split tasks smaller, one deliverable each.",
                         f"{pa}/{n} worker reports partial or at the context limit."))
    if sm["over_budget_rate"] is not None and sm["over_budget_rate"] > OVER_BUDGET_RATE_MAX:
        ob = sum(w["over_budget"] for w in ws)
        out.append(nudge("workers_over_budget", "Workers over their context budget: split tasks smaller, point them at exact files.",
                         f"{ob}/{sm['with_budget']} workers with a stated budget exceeded it; peak ctx p50 {sm['peak_ctx_p50']}."))
    if sm["gaps_rate"] is not None and sm["gaps_rate"] > GAPS_RATE_MAX:
        g = [w for w in ws if w["gaps"]]
        nc, nt = sum("commit" in w["gaps"] for w in g), sum("tests" in w["gaps"] for w in g)
        out.append(nudge("workers_report_gaps", "Reports lack commit hash/test result: require both on the report's first line in the prompt.",
                         f"{len(g)} reports miss what the prompt asked: {nc} no commit hash, {nt} no test result."))
    if sm["followup_calls_p50"] > FOLLOWUP_P50_MAX:
        out.append(nudge("workers_followup", "You re-check state after worker reports: ask workers for hash, test result and git status in the report.",
                         f"follow-up tool calls after a report p50 {sm['followup_calls_p50']} (n {n})."))
    return out


def scan(root, since, d1=None, workers=None):
    """U-scan: main transcripts <project>/<sid>.jsonl modified in the window -> sessions with their turns.
    When `workers` is a list, finished workers of each transcript are appended to it (U-workers)."""
    out = []
    for p in glob.glob(os.path.join(os.path.expanduser(root), "*", "*.jsonl")):
        if os.path.getmtime(p) < since.timestamp():
            continue
        sid = os.path.basename(p)[:-6]
        lines = list(read_lines(p))
        if workers is not None:
            workers += workers_of(lines, sid[:8], os.path.join(p[:-6], "subagents"), since)
        turns, name = parse(lines, sid[:8], since, d1)
        if turns:
            out.append({"sid": sid[:8], "name": name, "turns": turns})
    return out


def calibrate(turns):
    """U-calib: target words from replies followed by neutral (blended with the prior), capped by complained-long ones."""
    neutral = [c["reply_words"] for c in turns if c["next"] == "neutral" and c["reply_words"]]
    long_c = [c["reply_words"] for c in turns if c["theme"] == "length"]
    more = [c["reply_words"] for c in turns if c["next"] == "more"]
    med = pct(neutral, .5)
    target = TARGET_PRIOR_WORDS if med is None else (TARGET_PRIOR_WORDS * PRIOR_N + med * len(neutral)) / (PRIOR_N + len(neutral))
    if long_c:
        target = min(target, pct(long_c, .25) * (1 - TOLERANCE))
    target = max(MIN_REPLY_WORDS, int(round(target)))
    cur = pct([c["reply_words"] for c in turns if c["reply_words"]], .5) or 0
    verdict = "too_long" if cur > target * (1 + TOLERANCE) else "too_short" if cur < target * (1 - TOLERANCE) else "ok"
    why = (f"p50 reply {cur} words vs target {target} (prior {TARGET_PRIOR_WORDS} blended with p50 {med} of "
           f"{len(neutral)} replies followed by neutral; {len(long_c)} 'too long' complaints, {len(more)} 'more' requests).")
    return {"target_reply_words": target, "current_p50": cur, "verdict": verdict, "why": why}


def nudge(id_, text, evidence, severity="warn"):
    return {"id": id_, "text": text[:NUDGE_CHARS], "evidence": evidence, "severity": severity}


def nudges(turns, cal):
    """U-nudge: rules over the turns, named thresholds at the top."""
    n, out, target = len(turns), [], cal["target_reply_words"]
    if not n:
        return out
    over = sum(c["reply_words"] > target * (1 + TOLERANCE) for c in turns)
    if over / n >= LONG_REPLY_SHARE:
        out.append(nudge("long_replies", f"Answer first, then stop: keep replies under ~{target} words, no recap of steps.",
                         f"{over}/{n} replies over {int(target * (1 + TOLERANCE))} words; p50 {cal['current_p50']}."))
    vis = [c for c in turns if c["theme"] == "visible"]
    if len(vis) >= VISIBLE_REPEAT_MIN:
        out.append(nudge("verify_visible", "Before saying done, check the result is visible/working (run, open, screenshot) and say how you checked.",
                         f"{len(vis)} 'sigo sin ver/sigue sin'-style corrections in {n} turns."))
    ln = sum(c["theme"] == "length" for c in turns)
    if ln >= LENGTH_COMPLAINTS_MIN:
        out.append(nudge("length_complaints", "Shorter: one-line answer, then only what changed. No padding, no headers.",
                         f"{ln} 'too long'-style complaints in {n} turns."))
    chain = [c for c in turns if c["next"] in ("interrupt", "reject") and c["tool_calls"] >= LONG_CHAIN_TOOLS]
    if len(chain) >= LONG_CHAIN_MIN:
        out.append(nudge("long_chain", f"After ~{LONG_CHAIN_TOOLS} tool calls without reporting, pause and give a 1-line status.",
                         f"{len(chain)} interrupts/rejections after >= {LONG_CHAIN_TOOLS} tool calls."))
    asks = sum(c["asks"] for c in turns)
    if asks >= ASK_BACK_MIN and asks / n >= ASK_BACK_SHARE:
        out.append(nudge("ask_back", "Don't end with a question unless truly blocked; pick the sensible default and proceed.",
                         f"{asks}/{n} replies end with a question."))
    more = sum(c["next"] == "more" for c in turns)
    if more / n >= MORE_SHARE:
        out.append(nudge("too_short", "Add the key reason or number behind the answer; don't over-compress.",
                         f"{more}/{n} turns followed by a request for more detail.", "info"))
    corr = sum(c["next"] == "correction" for c in turns)
    if not out and corr:
        out.append(nudge("corrections", "Re-read the request before reporting; confirm each asked item is done.",
                         f"{corr}/{n} turns followed by a correction.", "info"))
    return out


PUBLIC = ("ts", "sid", "user_words", "reply_words", "code_words", "tool_calls", "subagents", "min", "next", "user_text", "reply_text")


def build(sessions, days, classifier, workers=None):
    turns = sorted((c for s in sessions for c in s["turns"]), key=lambda c: c["ts"])
    cnt = lambda ts_, k: sum(c["next"] == k for c in ts_)
    rw = [c["reply_words"] for c in turns if c["reply_words"]]  # U-overall: turns with a visible reply
    overall = {"turns": len(turns), "reply_words_p50": pct(rw, .5) or 0, "reply_words_p90": pct(rw, .9) or 0,
               "tools_per_turn_p50": pct([c["tool_calls"] for c in turns], .5) or 0,
               "turn_min_p50": float(pct([c["min"] for c in turns], .5) or 0.0),
               "interrupts": cnt(turns, "interrupt"), "rejections": cnt(turns, "reject"),
               "corrections": cnt(turns, "correction"), "more_requests": cnt(turns, "more"),
               "turns_with_code": sum(c["code_words"] > 0 for c in turns),
               "code_words_p50": pct([c["code_words"] for c in turns if c["code_words"]], .5) or 0}
    cal = calibrate(turns)
    ss = sorted(sessions, key=lambda s: s["turns"][-1]["ts"], reverse=True)[:TOP_SESSIONS]
    sess = [{"sid": s["sid"], "name": s["name"], "turns": len(s["turns"]),
             "reply_words_p50": pct([c["reply_words"] for c in s["turns"] if c["reply_words"]], .5) or 0,
             "corrections": cnt(s["turns"], "correction"), "interrupts": cnt(s["turns"], "interrupt"),
             "rejections": cnt(s["turns"], "reject"), "more_requests": cnt(s["turns"], "more"),
             "last": iso(s["turns"][-1]["ts"])} for s in ss]
    last = [dict({k: c[k] for k in PUBLIC}, ts=iso(c["ts"])) for c in turns[-LAST_TURNS:]]
    r = {"generated": iso(datetime.now(timezone.utc)), "window_days": int(days), "classifier": classifier,
         "overall": overall, "calibration": cal, "nudges": nudges(turns, cal), "sessions": sess, "turns": last}
    if workers is not None:
        r["workers"] = summarize_workers(workers)
        r["nudges"] += worker_nudges(workers, r["workers"])
    return r


def readout(r):
    """U-readout: compact section for readout.json."""
    o, c = r["overall"], r["calibration"]
    return {"turns": o["turns"], "reply_words_p50": o["reply_words_p50"], "target_reply_words": c["target_reply_words"],
            "verdict": c["verdict"], "corrections": o["corrections"], "interrupts": o["interrupts"],
            "rejections": o["rejections"], "nudges": [n["id"] for n in r["nudges"]], "detail": OUT}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=float, default=DAYS)
    ap.add_argument("--root", help=f"transcripts dir (default: config readers.paths.claude-code, else {ROOT})")
    ap.add_argument("--config")
    ap.add_argument("--out")
    ap.add_argument("--d1", action="store_true", help="scan: let d1 flip neutral -> more (off by default: no gain on test2)")
    ap.add_argument("--no-d1", action="store_true", help="eval: skip d1")
    ap.add_argument("--eval", nargs="?", const=os.path.join(os.path.dirname(os.path.abspath(__file__)), EVAL),
                    help="print heuristic vs d1 accuracy on the labelled prompts and exit")
    ap.add_argument("--holdout", action="store_true", help="--eval on the (former) held-out prompts")
    ap.add_argument("--test2", action="store_true", help="--eval on the test2 prompts (never used to tune)")
    a = ap.parse_args(argv)
    if a.holdout or a.test2:
        a.eval = os.path.join(os.path.dirname(os.path.abspath(__file__)), TEST2 if a.test2 else HOLDOUT)
    if a.eval:
        print(json.dumps(evaluate([json.loads(l) for l in open(a.eval)], None if a.no_d1 else D1()), indent=1))
        return
    cfg = load_config(a.config)
    since = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=a.days)
    d1 = D1() if a.d1 else None  # U-eval: the heuristic alone ties the combined classifier on test2
    t = time.time()
    ws = []
    sessions = scan(a.root or cfg["readers"]["paths"].get(HARNESS) or ROOT, since, d1, ws)
    r = build(sessions, a.days, "d1" if d1 and d1.used else "heuristic", ws)
    out = a.out or data_dir(cfg)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, OUT), "w") as f:
        json.dump(r, f, indent=1)
    o, c = r["overall"], r["calibration"]
    print(f"orch_ux: {o['turns']} turns in {len(sessions)} sessions, reply p50 {o['reply_words_p50']} vs target "
          f"{c['target_reply_words']} ({c['verdict']}), {o['corrections']} corrections, {o['interrupts']} interrupts, "
          f"classifier {r['classifier']}, {len(r['nudges'])} nudges, {len(ws)} workers, {time.time() - t:.1f}s -> {os.path.join(out, OUT)}")


if __name__ == "__main__":
    main()
