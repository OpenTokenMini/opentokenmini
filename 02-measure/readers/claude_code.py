"""Claude Code transcripts: ~/.claude/projects/**/*.jsonl. Specs R-claude-* in readers/METHOD.md."""
import glob, json, os
from common import root, recent, ts_ok, event, make_tokens

ROOT = "~/.claude/projects"
SKIP_MODELS = ("<synthetic>",)  # locally generated messages, not API calls


def is_prompt(d):
    """R-claude-prompt: a human turn = user line, not meta/sidechain, with string content or a text block."""
    if d.get("type") != "user" or d.get("isMeta") or d.get("isSidechain"):
        return False
    c = (d.get("message") or {}).get("content")
    return isinstance(c, str) or (isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "text" for b in c))


def agent_type(path):
    """R-claude-agent-type: a subagent transcript agent-<id>.jsonl has agent-<id>.meta.json next to it with agentType."""
    try:
        with open(path[:-len(".jsonl")] + ".meta.json") as f:
            t = json.load(f).get("agentType")
        return t if isinstance(t, str) and t else None
    except (OSError, ValueError, AttributeError):
        return None


def read(since, cfg):
    calls = {}  # R-claude-dedup: request id -> call; a response is logged once per content block
    for path in glob.glob(os.path.join(root(cfg, "claude-code", ROOT), "**", "*.jsonl"), recursive=True):
        if not recent(path, since):
            continue
        atype = agent_type(path)
        with open(path, errors="replace") as f:
            for line in f:
                if '"assistant"' not in line and '"user"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                ts = d.get("timestamp", "")
                if not ts_ok(ts, since):
                    continue
                if is_prompt(d):
                    yield event("user_prompt", ts, "claude-code", d.get("sessionId"), cwd=d.get("cwd"))
                if d.get("type") != "assistant":
                    continue
                m = d.get("message") or {}
                u, model = m.get("usage"), m.get("model")
                if not u or model in SKIP_MODELS:
                    continue
                rid = d.get("requestId") or m.get("id")
                c = calls.setdefault(rid, {"ts": ts, "sid": d.get("sessionId"), "cwd": d.get("cwd"), "model": model,
                                           "sub": bool(d.get("isSidechain")), "tools": set(), "atype": atype,
                                           "error": "api_error" if d.get("isApiErrorMessage") else None})
                c["u"] = u  # last block wins: usage repeats, final counts are complete
                c["stop"] = c.get("stop") or m.get("stop_reason")
                c["tools"].update(b.get("name") for b in m.get("content") or []
                                  if isinstance(b, dict) and b.get("type") == "tool_use")
    for rid, c in calls.items():
        u, cc = c["u"], c["u"].get("cache_creation") or {}
        tokens = make_tokens(input=u.get("input_tokens"), output=u.get("output_tokens"),
                             cache_read=u.get("cache_read_input_tokens"), cache_write=u.get("cache_creation_input_tokens"),
                             cache_write_5m=cc.get("ephemeral_5m_input_tokens"),
                             cache_write_1h=cc.get("ephemeral_1h_input_tokens"))  # R-claude-ttl
        error = c["error"] or (None if c["stop"] else "truncated")  # R-claude-truncated
        yield event("api_call", c["ts"], "claude-code", c["sid"], cwd=c["cwd"], request_id=rid, subagent=c["sub"],
                    model=c["model"], provider="anthropic", tokens=tokens, error=error, tools=c["tools"],
                    agent_type=c["atype"])
