#!/usr/bin/env python3
"""Raw OTLP records (otel/<signal>-YYYY-MM-DD.jsonl) -> events/otel.jsonl (schemas/event.schema.json).

Specs: collector/METHOD.md (N-*). Run from the repo root:
python3 02-measure/collector/normalize.py [--days N] [--harness ID] [--config PATH] [--in RAW_DIR] [--out EVENTS_DIR]
"""
import argparse, glob, hashlib, json, os, re, sys
from datetime import datetime, timedelta, timezone

import pathlib  # numbered stage dirs aren't importable: find the repo, put 02-measure/ on sys.path
REPO = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir())
sys.path.insert(0, str(REPO / "02-measure"))
from schemas.config import load_config, data_dir
from schemas.cost import load_prices, make_tokens, event_cost, zero_tokens, zero_cost, price_for, list_cost
from schemas.check import validate

HASH_LEN = 12  # N-user: sha256 hex chars, same as the collector's N-identity
UNKNOWN_PROJECT = "unknown"  # N-project: OTel source carries no working directory
SIGNALS = ("logs", "traces")  # N-signals: metrics duplicate the log events and are not read
USER_KEYS = ("user.email", "user.account_uuid", "user.id", "ai.telemetry.metadata.userId")
OPENCODE_SPANS = ("ai.streamText.doStream", "ai.generateText.doGenerate")  # N-opencode: one per LLM request
ACCEPT = {"accept", "approved", "approved_for_session", "allow"}  # N-decision
REJECT = {"reject", "denied", "deny", "abort"}
SALT = os.environ.get("OTM_ID_SALT", "")  # N-user: same salt as the collector's N-identity, so raw emails in old files hash to the same id
SPLIT_UNKNOWN = "unknown"  # N-claude-ttl: OTel cache_creation_tokens has no 5m/1h split
HEX = re.compile(r"^[0-9a-f]{%d}$" % HASH_LEN)


def val(v):
    """OTLP AnyValue -> python (intValue strings -> int)."""
    if not isinstance(v, dict) or not v:
        return None
    k, x = next(iter(v.items()))
    if k == "intValue":
        return int(x)
    if k == "arrayValue":
        return [val(i) for i in x.get("values", [])]
    if k == "kvlistValue":
        return {a["key"]: val(a.get("value")) for a in x.get("values", [])}
    return x


def attrs(lst):
    return {a["key"]: val(a.get("value")) for a in lst or [] if "key" in a}


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def iso_ns(ns):
    return datetime.fromtimestamp(int(ns) / 1e9, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def user_hash(a):
    """N-user: first identity attribute present, sha256[:HASH_LEN]; collector-hashed values kept."""
    v = next((str(a[k]) for k in USER_KEYS if a.get(k)), None)
    if v is None:
        return None
    return v if HEX.match(v) else hashlib.sha256((SALT + v).encode()).hexdigest()[:HASH_LEN]


def harness_of(service):
    """N-harness: service.name -> harness id (None = not a known harness, skipped)."""
    s = (service or "").lower()
    if s == "claude-code":
        return "claude-code"
    if s.startswith("codex"):
        return "codex"
    if s in ("opencode", "pi"):
        return s
    return None


def base(kind, harness, ts, session_id, a):
    return {"v": 1, "kind": kind, "ts": ts, "harness": harness, "source": "otel", "session_id": str(session_id),
            "request_id": None, "parent_session_id": None, "subagent": False, "user": user_hash(a),
            "project": UNKNOWN_PROJECT, "repo": None, "model": None, "provider": None,
            "tokens": zero_tokens(), "cost": zero_cost(), "cost_basis": "unknown", "duration_ms": None,
            "error": None, "retries": 0, "tools": [], "tool": None, "decision": None, "decision_source": None}


def priced(e, prices, reported_total=None):
    e["cost"], e["cost_basis"] = event_cost(e["tokens"], e["model"], prices, reported_total=reported_total)
    return e


def decision(e, a, tool_key, src_key):
    d = str(a.get("decision") or "").lower()
    e["tool"], e["decision_source"] = a.get(tool_key) or "unknown", a.get(src_key)
    e["decision"] = "accept" if d in ACCEPT else "reject" if d in REJECT else None
    return e if e["decision"] else None


def claude_log(rec, a, prices):
    """N-claude: api_request, api_error, user_prompt, tool_decision log events."""
    name = a.get("event.name") or str((rec.get("body") or {}).get("stringValue", "")).removeprefix("claude_code.")
    sid = a.get("session.id")
    if not sid:
        return None
    ts = a.get("event.timestamp") or iso_ns(rec.get("timeUnixNano") or rec.get("observedTimeUnixNano") or 0)
    if name in ("api_request", "api_error"):
        e = base("api_call", "claude-code", ts, sid, a)
        e.update(request_id=a.get("request_id"), model=a.get("model"), provider="anthropic",
                 subagent=str(a.get("query_source") or "").startswith("agent:"), duration_ms=num(a.get("duration_ms")),
                 query_source=a.get("query_source"), agent_name=a.get("agent.name"))  # N-claude-agent
        if name == "api_error":
            e["error"] = str(a.get("error") or a.get("status_code") or "api_error")[:200]
            e["retries"] = max(0, int(num(a.get("attempt")) or 1) - 1)
            return priced(e, prices)
        w5, w1 = a.get("cache_creation_5m_tokens"), a.get("cache_creation_1h_tokens")
        e["tokens"] = make_tokens(a.get("input_tokens"), a.get("output_tokens"),
                                  a.get("cache_read_tokens"), a.get("cache_creation_tokens"),
                                  cache_write_5m=w5, cache_write_1h=w1)
        e = priced(e, prices, num(a.get("cost_usd")))
        return e if w5 is not None or w1 is not None else ttl_upper(e, prices)  # N-claude-ttl only without the split
    if name == "user_prompt":
        return base("user_prompt", "claude-code", ts, sid, a)
    if name == "tool_decision":
        return decision(base("tool_decision", "claude-code", ts, sid, a), a, "tool_name", "source")
    return None


def ttl_upper(e, prices):
    """N-claude-ttl: cache writes of unknown TTL priced as all 1h (upper bound) when that beats cost_usd; flagged."""
    p = price_for(e["model"], prices)
    if not e["tokens"]["cache_write"] or not p:
        return e
    e["cache_split"] = SPLIT_UNKNOWN
    up = list_cost(e["tokens"], {**p, "cache_write": p.get("cache_write_1h", p["cache_write"])})
    if up["total"] > e["cost"]["total"]:
        e["cost"], e["cost_basis"] = up, "list_price"
    return e


def codex_log(rec, a, prices):
    """N-codex: codex.sse_event response.completed (tokens), failed sse events, codex.user_prompt, codex.tool_decision."""
    name, sid = a.get("event.name"), a.get("conversation.id")
    if not sid:
        return None
    ts = a.get("event.timestamp") or iso_ns(rec.get("timeUnixNano") or rec.get("observedTimeUnixNano") or 0)
    if name == "codex.sse_event" and not a.get("error.message") and is_prewarm(a):
        return None
    if name == "codex.sse_event" and ("input_token_count" in a or a.get("error.message")):
        e = base("api_call", "codex", ts, sid, a)
        e.update(model=a.get("model"), provider="openai", duration_ms=num(a.get("duration_ms")))
        if a.get("error.message"):
            e["error"] = str(a["error.message"])[:200]
            return priced(e, prices)
        e["tokens"] = make_tokens(a.get("input_token_count"), a.get("output_token_count"), a.get("cached_token_count"),
                                  a.get("cache_write_token_count"), a.get("reasoning_token_count"),
                                  input_includes_cache=True, output_includes_reasoning=True)
        return priced(e, prices)
    if name == "codex.user_prompt":
        return base("user_prompt", "codex", ts, sid, a)
    if name == "codex.tool_decision":
        return decision(base("tool_decision", "codex", ts, sid, a), a, "tool_name", "source")
    return None


def is_prewarm(a):
    """N-codex-prewarm: startup websocket warmup (generate=false) completes with 0 output and no ttft_ms; not in rollouts."""
    return "input_token_count" in a and not int(num(a.get("output_token_count")) or 0) and "ttft_ms" not in a


def pi_log(rec, a, prices):
    """N-pi: pi.api_request records from the pi-telemetry extension."""
    if str((rec.get("body") or {}).get("stringValue")) != "pi.api_request" or not a.get("session.id"):
        return None
    e = base("api_call", "pi", iso_ns(rec.get("timeUnixNano") or 0), a["session.id"], a)
    e.update(model=a.get("model"), provider=a.get("provider"),
             project=os.path.basename(str(a.get("cwd") or "").rstrip("/")) or UNKNOWN_PROJECT,
             tools=[t for t in str(a.get("tools") or "").split(",") if t])
    if a.get("stop_reason") in ("error", "aborted"):
        e["error"] = str(a["stop_reason"])
    e["tokens"] = make_tokens(a.get("input_tokens"), a.get("output_tokens"), a.get("cache_read_tokens"),
                              a.get("cache_creation_tokens"), a.get("reasoning_tokens"))
    return priced(e, prices, num(a.get("cost_usd")) if "cost_usd" in a else None)


def opencode_span(sp, a, prices):
    """N-opencode: AI SDK doStream/doGenerate spans; usage attrs inclusive (AI SDK semantics)."""
    sid = a.get("session.id") or a.get("ai.telemetry.metadata.sessionId")
    if sp.get("name") not in OPENCODE_SPANS or not sid:
        return None
    e = base("api_call", "opencode", iso_ns(sp.get("endTimeUnixNano") or sp.get("startTimeUnixNano") or 0), sid, a)
    e.update(model=a.get("ai.model.id"),  # N-opencode-id: x-opencode-request is the user message id, shared by retries/steps
             provider=a.get("ai.model.provider"), project=a.get("ai.request.headers.x-opencode-project") or UNKNOWN_PROJECT,
             duration_ms=(int(sp.get("endTimeUnixNano", 0)) - int(sp.get("startTimeUnixNano", 0))) / 1e6 or None)
    if (sp.get("status") or {}).get("code") in (2, "STATUS_CODE_ERROR"):
        e["error"] = str(sp["status"].get("message") or "error")[:200]
    g = lambda *ks: next((a[k] for k in ks if a.get(k) is not None), 0)
    e["tokens"] = make_tokens(g("ai.usage.inputTokens", "ai.usage.promptTokens", "gen_ai.usage.input_tokens"),
                              g("ai.usage.outputTokens", "ai.usage.completionTokens", "gen_ai.usage.output_tokens"),
                              g("ai.usage.cachedInputTokens"), 0, g("ai.usage.reasoningTokens"),
                              input_includes_cache=True, output_includes_reasoning=True)
    return priced(e, prices)


LOG_MAPPERS = {"claude-code": claude_log, "codex": codex_log, "pi": pi_log}
SPAN_MAPPERS = {"opencode": opencode_span}


def raw_records(raw_dir):
    """N-raw-read: v1 and legacy lines; undecoded/data_b64-only and unparsable lines are counted, not read."""
    skipped = 0
    for sig in SIGNALS:
        for path in sorted(glob.glob(os.path.join(raw_dir, f"{sig}-*.jsonl"))):
            with open(path) as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        skipped += 1
                        continue
                    if isinstance(r.get("data"), dict):
                        yield sig, r["data"]
                    else:
                        skipped += 1
    raw_records.skipped = skipped


def events_from(signal, data, prices):
    rkey, skey, ikey = (("resourceLogs", "scopeLogs", "logRecords") if signal == "logs"
                        else ("resourceSpans", "scopeSpans", "spans"))
    for res in data.get(rkey) or []:
        ra = attrs((res.get("resource") or {}).get("attributes"))
        h = harness_of(ra.get("service.name"))
        fn = (LOG_MAPPERS if signal == "logs" else SPAN_MAPPERS).get(h)
        if not fn:
            continue
        for sc in res.get(skey) or []:
            for it in sc.get(ikey) or []:
                e = fn(it, {**ra, **attrs(it.get("attributes"))}, prices)
                if e:
                    yield e


def dedup_key(e):
    """N-dedup: successful api_call by request_id; anything else by its full content."""
    if e["kind"] == "api_call" and e["request_id"] and not e["error"]:
        return (e["harness"], e["kind"], e["request_id"])
    return json.dumps(e, sort_keys=True)


def normalize(raw_dir, since=None, harness=None, prices=None):
    prices = prices if prices is not None else load_prices()
    seen, out = set(), []
    for sig, data in raw_records(raw_dir):
        for e in events_from(sig, data, prices):
            if (harness and e["harness"] != harness) or (since and e["ts"] < since):
                continue
            k = dedup_key(e)
            if k not in seen:
                seen.add(k)
                out.append(e)
    out.sort(key=lambda e: (e["ts"], e["harness"], e["session_id"]))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=float)
    ap.add_argument("--harness")
    ap.add_argument("--config")
    ap.add_argument("--in", dest="raw", help="raw dir (default <data>/otel)")
    ap.add_argument("--out", help="events dir (default <data>/events); writes otel.jsonl there")
    a = ap.parse_args()
    root = data_dir(load_config(a.config))
    since = None
    if a.days:
        since = (datetime.now(timezone.utc) - timedelta(days=a.days)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    evs = normalize(a.raw or os.path.join(root, "otel"), since, a.harness)
    bad = [(i, err) for i, e in enumerate(evs) for err in validate(e, "event")]
    for i, err in bad[:20]:
        print(f"event {i}: {err}", file=sys.stderr)
    out_dir = a.out or os.path.join(root, "events")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "otel.jsonl")
    with open(path + ".tmp", "w") as f:
        for e in evs:
            f.write(json.dumps(e, separators=(",", ":")) + "\n")
    os.replace(path + ".tmp", path)
    counts = {}
    for e in evs:
        counts.setdefault(e["harness"], {}).setdefault(e["kind"], 0)
        counts[e["harness"]][e["kind"]] += 1
    print(json.dumps({"out": path, "events": len(evs), "skipped_raw": raw_records.skipped, "invalid": len(bad),
                      "by_harness": counts}), file=sys.stderr)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
