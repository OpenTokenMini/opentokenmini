"""Regenerate the analyze fixture: python3 tests/fixtures/analyze/gen.py tests/fixtures/analyze/events"""
import json, os, sys
out = sys.argv[1]; os.makedirs(out, exist_ok=True)
def ev(h, src, sid, kind, ts, rid=None, c=0.0, model=None, basis="unknown", tools=(), sub=False, err=None, retries=0, tool=None, dec=None, dsrc=None):
    api = kind == "api_call"
    tok = {"input": 100, "output": 50, "cache_read": 1000, "cache_write": 0, "reasoning": 0} if api else dict.fromkeys(["input","output","cache_read","cache_write","reasoning"], 0)
    cost = {"input": c*0.25, "output": c*0.5, "cache_read": c*0.25, "cache_write": 0.0}
    cost["total"] = sum(cost.values())
    return {"v": 1, "kind": kind, "ts": ts, "harness": h, "source": src, "session_id": sid, "request_id": rid,
            "parent_session_id": None, "subagent": sub, "user": "0123456789ab", "project": "demo/" + h,
            "repo": "/home/user/projects/demo", "model": model, "provider": None, "tokens": tok, "cost": cost,
            "cost_basis": basis if api else "unknown", "duration_ms": 1000 if api else None, "error": err,
            "retries": retries, "tools": list(tools), "tool": tool, "decision": dec, "decision_source": dsrc}
otel, tr = [], []
ts = lambda d, h, s: f"2026-10-{d:02d}T{h:02d}:00:{s:02d}Z"
M = "claude-sonnet-4"
for i in range(1, 11):
    sid = f"s-cc-{i:02d}"
    ca, cb = (1.0, 1.0) if i == 10 else (0.10, round(0.10 + 0.01 * i, 2))
    tb = ["mcp__git__log", "Read"] if i == 3 else ["Bash"]
    a = dict(model=M, basis="reported", tools=["Bash"])
    b = dict(model=M, basis="reported", tools=tb, sub=(i == 4), err=("500" if i == 3 else None), retries=(1 if i == 3 else 0))
    otel += [ev("claude-code", "otel", sid, "user_prompt", ts(1, i, 0)),
             ev("claude-code", "otel", sid, "api_call", ts(1, i, 10), f"r{i}a", ca, **a)]
    otel.append(ev("claude-code", "otel", sid, "api_call", f"2026-10-01T{i:02d}:01:10Z", f"r{i}b", cb, **b))
    if i == 2:   # rule 1: same-source repeat
        otel.append(ev("claude-code", "otel", sid, "api_call", f"2026-10-01T{i:02d}:01:11Z", f"r{i}b", cb, **b))
    a["basis"] = b["basis"] = "list_price"
    tr += [ev("claude-code", "transcript", sid, "user_prompt", ts(1, i, 2)),          # rule 3
           ev("claude-code", "transcript", sid, "api_call", ts(1, i, 12), f"r{i}a", ca, **a),   # rule 2
           ev("claude-code", "transcript", sid, "api_call", f"2026-10-01T{i:02d}:01:12Z", f"r{i}b", cb, **b)]
    if i == 1:   # rule 3 on api_call with null id
        tr.append(ev("claude-code", "transcript", sid, "api_call", ts(1, i, 20), None, 0.5, model=M, basis="list_price"))
sid = "s-cc-11"   # transcript only: kept
tr += [ev("claude-code", "transcript", sid, "user_prompt", ts(2, 9, 0)),
       ev("claude-code", "transcript", sid, "api_call", ts(2, 9, 30), "r11a", 0.24, model=M, basis="list_price", tools=["Bash"])]
for i in range(1, 4):
    sid = f"s-cx-{i}"
    tr += [ev("codex", "transcript", sid, "user_prompt", ts(2, 10 + i, 0)),
           ev("codex", "transcript", sid, "api_call", ts(2, 10 + i, 5), None, 0.01, model="gpt-5", basis="list_price"),
           ev("codex", "transcript", sid, "api_call", ts(2, 10 + i, 9), None, 0.01, model="gpt-5", basis="list_price")]
tr += [ev("codex", "transcript", "s-cx-1", "tool_decision", ts(2, 11, 6), tool="shell", dec="accept", dsrc="user"),
       ev("codex", "transcript", "s-cx-1", "tool_decision", ts(2, 11, 7), tool="apply_patch", dec="reject", dsrc="config")]
otel += [ev("opencode", "otel", "s-oc-1", "user_prompt", ts(3, 8, 0)),
         ev("opencode", "otel", "s-oc-1", "api_call", ts(3, 8, 4), "o1", 0.0)]
for name, rows in (("otel.jsonl", otel), ("transcript.jsonl", tr)):
    with open(os.path.join(out, name), "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)
print(len(otel), len(tr))
