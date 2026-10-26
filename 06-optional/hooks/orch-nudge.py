#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook: nudge the orchestrator from the current session's UX signals.

Reads the hook JSON on stdin (transcript_path, prompt). Parses the tail of the current transcript with the heuristics of
04-auto-analysis/orch-ux/orch_ux.py (no d1, no network), classifies the incoming prompt as the reaction to the last reply,
checks this session's workers finished in the last hour (partial / over budget),
and prints at most MAX_LINES short lines (added to the agent's context) only when a rule fires; otherwise prints nothing.
Merges with the nudges of the latest orch_ux.json in the data dir when present. Never fails the prompt: any error -> silent, exit 0.
"""
import glob, importlib.util, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ANALYZER = os.path.join(HERE, "..", "..", "04-auto-analysis", "orch-ux", "orch_ux.py")
LAST_N = 8              # turns of the current session looked at
TAIL_BYTES = 1_500_000  # only the end of the transcript is read (speed)
MAX_LINES = 2
CHAIN_TOOLS = 8         # an interrupt/reject after this many tool calls in the turn -> long_chain
LONG_MIN_TURNS = 3      # long_replies needs at least this many recent replies
ASK_BACK_RECENT = 4     # ask_back: of the last this many replies...
ASK_BACK_MIN = 2        # ...at least this many end with a question
WORKER_WINDOW_S = 3600      # workers_partial: subagent transcripts modified in the last this many seconds
WORKER_TAIL_BYTES = 200_000 # only the end of each worker transcript is read (final report + peak context)
PREFIX = "[orch-nudge] "


def load_analyzer():
    spec = importlib.util.spec_from_file_location("orch_ux", ANALYZER)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def global_report(ux, path=None):
    try:
        if path is None:
            path = os.path.join(ux.data_dir(ux.load_config(None)), ux.OUT)
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def fire(ux, transcript, prompt, report):
    """Session rules -> list of (id, local text). The prompt is the human's reaction to the last turn."""
    turns, _ = ux.parse(ux.read_lines(transcript, TAIL_BYTES))
    if turns and prompt and turns[-1]["user_text"] == ux.snip(prompt):
        turns = turns[:-1]  # the prompt is already logged: it is the pending turn, not a finished one
    turns = turns[-LAST_N:]
    if not turns:
        return []
    last, out = turns[-1], []
    if prompt and last["next"] is None:
        last["next"], last["theme"] = ux.heuristic(prompt)
    if last["theme"] == "visible":
        out.append(("verify_visible", "He still can't see/use what he asked for: check it yourself (run/open/screenshot) before reporting."))
    if last["theme"] == "length":
        out.append(("length_complaints", "He found the last reply too long: answer in 1-3 lines, answer first."))
    if last["next"] in ("interrupt", "reject") and last["tool_calls"] >= CHAIN_TOOLS:
        out.append(("long_chain", f"He stopped you after {last['tool_calls']} tool calls: re-read his request, give a 1-line status."))
    target = (report.get("calibration") or {}).get("target_reply_words") or ux.TARGET_PRIOR_WORDS
    rw = [c["reply_words"] for c in turns if c["reply_words"]]
    if len(rw) >= LONG_MIN_TURNS and ux.pct(rw, .5) > target * (1 + ux.TOLERANCE):
        out.append(("long_replies", f"Recent replies p50 {ux.pct(rw, .5)} words vs target {target}: shorter, answer first."))
    if sum(c["asks"] for c in turns[-ASK_BACK_RECENT:]) >= ASK_BACK_MIN and last["asks"]:
        out.append(("ask_back", "Stop ending replies with questions; pick the sensible default and proceed."))
    return out


def worker_status(ux, path):
    """(report, peak ctx) of a finished worker transcript, None while it is still running (last assistant msg not text-only)."""
    first = next(ux.read_lines(path), None) or {}
    prompt = (first.get("message") or {}).get("content")
    prompt = prompt if isinstance(prompt, str) else ""
    last, peak = None, 0
    for d in ux.read_lines(path, WORKER_TAIL_BYTES):
        if d.get("type") != "assistant":
            continue
        last = ux.blocks(d)
        u = (d.get("message") or {}).get("usage") or {}
        peak = max(peak, sum(u.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")))
    if not last or any(b.get("type") == "tool_use" for b in last):
        return None
    report = "\n".join(b.get("text", "") for b in last if b.get("type") == "text").strip()
    return (report, prompt, peak) if report else None


def worker_rule(ux, transcript, now=None):
    """workers_partial: finished workers of this session in the last WORKER_WINDOW_S that were partial or over their budget."""
    sub = os.path.join(transcript[:-len(".jsonl")] if transcript.endswith(".jsonl") else transcript, "subagents")
    now = now or time.time()
    part = over = 0
    for p in glob.glob(os.path.join(sub, "agent-*.jsonl")):
        if now - os.path.getmtime(p) > WORKER_WINDOW_S:
            continue
        st = worker_status(ux, p)
        if not st:
            continue
        g = ux.grade(st[0], st[1])
        part += g["partial"]
        over += bool(g["budget"] and st[2] > g["budget"])
    if not part and not over:
        return []
    what = " and ".join(x for x in (f"{part} partial" if part else "", f"{over} over budget" if over else "") if x)
    return [("workers_partial", f"Workers last hour: {what}. Split tasks smaller and state a context budget the worker can meet.")]


def lines(ux, hook, report):
    tp = hook.get("transcript_path") or ""
    fired = fire(ux, tp, hook.get("prompt") or "", report) + worker_rule(ux, tp)
    if not fired:
        return []
    glob_ = {n["id"]: n for n in report.get("nudges") or []}
    out = [t for _, t in fired]
    ids = {i for i, _ in fired}
    out += [n["text"] for i, n in glob_.items() if i not in ids and n.get("severity") == "warn"]
    return [PREFIX + t[:ux.NUDGE_CHARS] for t in out[:MAX_LINES]]


def main(stdin=sys.stdin, stdout=sys.stdout, report_path=None):
    try:
        hook = json.load(stdin)
        ux = load_analyzer()
        for l in lines(ux, hook, global_report(ux, report_path)):
            print(l, file=stdout)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
