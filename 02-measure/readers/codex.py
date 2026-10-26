"""Codex CLI rollouts: ~/.codex/sessions/**/rollout-*.jsonl. Specs R-codex-* in readers/METHOD.md."""
import glob, os
from types import SimpleNamespace
from common import root, recent, ts_ok, event, jsonl, make_tokens

ROOT = "~/.codex/sessions"
TOOL_ITEMS = {"function_call": None, "custom_tool_call": None, "local_shell_call": "shell", "web_search_call": "web_search"}
USAGE_KEYS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens", "reasoning_output_tokens")


def delta(total, prev):
    """R-codex-delta: per-call usage = cumulative total minus the previous cumulative total."""
    return {k: (total or {}).get(k, 0) - (prev or {}).get(k, 0) for k in USAGE_KEYS}


def usage(info, prev):
    """R-codex-delta; a counter reset (negative delta) falls back to last_token_usage."""
    u = delta(info.get("total_token_usage"), prev)
    if any(v < 0 for v in u.values()):
        last = info.get("last_token_usage") or {}
        u = {k: last.get(k, 0) for k in USAGE_KEYS}
    return u


def read(since, cfg):
    for path in glob.glob(os.path.join(root(cfg, "codex", ROOT), "**", "rollout-*.jsonl"), recursive=True):
        if recent(path, since):
            yield from read_file(path, since)


def read_file(path, since):
    s = SimpleNamespace(sid=os.path.basename(path), parent=None, cwd=None, model=None, provider="openai", tools=set(), prev=None)
    for d in jsonl(path):
        on = ON.get(d.get("type"))
        if on:
            yield from on(s, d.get("payload") or {}, d.get("timestamp", ""), since)


def session_meta(s, p, ts, since):
    s.sid, s.cwd, s.provider = p.get("id") or s.sid, p.get("cwd"), p.get("model_provider") or s.provider
    s.parent = spawn_parent(p.get("source")) or s.parent
    return ()


def turn_context(s, p, ts, since):
    s.model, s.cwd = p.get("model") or s.model, p.get("cwd") or s.cwd
    return ()


def response_item(s, p, ts, since):
    if p.get("type") in TOOL_ITEMS:
        s.tools.add(p.get("name") or TOOL_ITEMS[p["type"]])
    return ()


def spawn_parent(src):
    """None = not a subagent; else the parent thread id, or "unknown" when the spawn record lacks it."""
    spawn = (src.get("subagent") or {}) if isinstance(src, dict) else None
    if spawn is None:
        return None
    return ((spawn.get("thread_spawn") or {}).get("parent_thread_id") if isinstance(spawn, dict) else None) or "unknown"


def event_msg(s, p, ts, since):
    t = p.get("type")
    if t == "token_count" and p.get("info"):
        yield from token_count(s, p["info"], ts, since)
    elif ts_ok(ts, since) and is_prompt(t, p):
        yield emit(s, "user_prompt", ts)


def is_prompt(t, p):
    return t == "user_message" or (t == "item_completed" and (p.get("item") or {}).get("type") == "UserMessage")


def token_count(s, info, ts, since):
    total = info.get("total_token_usage")
    if total == s.prev:  # R-codex-repeat: same running total logged again, not a new call
        return
    u, s.prev = usage(info, s.prev), total
    if ts_ok(ts, since):
        tokens = make_tokens(input=u["input_tokens"], output=u["output_tokens"],
                             cache_read=u["cached_input_tokens"], cache_write=u["cache_write_input_tokens"],
                             reasoning=u["reasoning_output_tokens"],
                             input_includes_cache=True, output_includes_reasoning=True)
        yield emit(s, "api_call", ts, model=s.model, provider=s.provider, tokens=tokens, tools=s.tools)
    s.tools = set()


def emit(s, kind, ts, **extra):
    return event(kind, ts, "codex", s.sid, cwd=s.cwd, parent=s.parent if s.parent != "unknown" else None,
                 subagent=s.parent is not None, **extra)


ON = {"session_meta": session_meta, "turn_context": turn_context, "response_item": response_item, "event_msg": event_msg}  # record type -> handler(state, payload, ts, since) -> events
