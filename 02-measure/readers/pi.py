"""Pi coding agent sessions: ~/.pi/agent/sessions/<cwd>/*.jsonl. Specs R-pi-* in readers/METHOD.md."""
import glob, os
from common import root, recent, ts_ok, event, jsonl, make_tokens

ROOT = os.path.join(os.environ.get("PI_CODING_AGENT_DIR", "~/.pi/agent"), "sessions")
COST_KEYS = {"input": "input", "output": "output", "cache_read": "cacheRead", "cache_write": "cacheWrite"}


def reported(u):
    """R-pi-cost: per-type USD when Pi logged a non-zero total, else None (fall back to C-cost)."""
    c = u.get("cost") or {}
    return {k: c.get(src) or 0 for k, src in COST_KEYS.items()} if c.get("total") else None


def read(since, cfg):
    for path in glob.glob(os.path.join(root(cfg, "pi", ROOT), "*", "*.jsonl")):
        if not recent(path, since):
            continue
        sid, cwd = os.path.basename(path), None
        for d in jsonl(path):
            if d.get("type") == "session":
                sid, cwd = d.get("id") or sid, d.get("cwd")
                continue
            ts = d.get("timestamp", "")
            if not ts_ok(ts, since):
                continue
            m = d.get("message") or {}
            if m.get("role") == "user":
                yield event("user_prompt", ts, "pi", sid, cwd=cwd)
                continue
            u = m.get("usage") if m.get("role") == "assistant" else d.get("usage")  # R-pi-calls: also compaction
            if not u:
                continue
            tokens = make_tokens(input=u.get("input"), output=u.get("output"), cache_read=u.get("cacheRead"),
                                 cache_write=u.get("cacheWrite"), reasoning=u.get("reasoning"),
                                 output_includes_reasoning=True)
            model = m.get("model") or d.get("model")
            yield event("api_call", ts, "pi", sid, cwd=cwd, request_id=d.get("id"),
                        model=os.path.basename(model) if model else None, provider=m.get("provider"), tokens=tokens,
                        reported=reported(u), error="error" if m.get("stopReason") == "error" else None,
                        tools={b.get("name") for b in m.get("content") or [] if isinstance(b, dict) and b.get("type") == "toolCall"})
