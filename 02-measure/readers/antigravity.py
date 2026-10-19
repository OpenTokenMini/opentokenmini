"""Antigravity (agy) conversations: protobuf rows in ~/.gemini/antigravity*/conversations/*.db. Specs R-agy-*.
Field numbers read from the descriptors embedded in the agy binary; stdlib wire-format parser, one level at a time."""
import collections, glob, json, os, sqlite3
from common import root, recent, event, iso, make_tokens

ROOTS = ["~/.gemini/antigravity-cli/conversations", "~/.gemini/antigravity/conversations"]
META = "~/.gemini/antigravity-cli/cache/conversation_metadata.json"
USER_INPUT, PLANNER_RESPONSE = 14, 15  # CortexStepType
coverage = {}  # R-agy-coverage: path -> reason a conversation was skipped; printed by readers.py


def varint(b, i):
    r = s = 0
    while True:
        x = b[i]; i += 1; r |= (x & 0x7F) << s; s += 7
        if x < 0x80:
            return r, i


def pb(b):
    """Protobuf wire format -> {field: [values]}; nested messages stay bytes."""
    out, i = collections.defaultdict(list), 0
    while i < len(b):
        key, i = varint(b, i)
        f, w = key >> 3, key & 7
        if w == 0:
            v, i = varint(b, i)
        elif w == 2:
            n, i = varint(b, i); v = b[i:i + n]; i += n
        elif w in (1, 5):
            n = 8 if w == 1 else 4; v = b[i:i + n]; i += n
        else:
            raise ValueError(f"wire type {w}")
        out[f].append(v)
    return out


def packed(b):
    out, i = [], 0
    while i < len(b):
        v, i = varint(b, i); out.append(v)
    return out


def first(m, f, default=None):
    return m[f][0] if m.get(f) else default


def models_by_step(db):
    """gen_metadata: CortexStepGeneratorMetadata{1 chat_model{19 response_model}, 2 step_indices}."""
    models = {}
    for (g,) in db.execute("select data from gen_metadata"):
        g = pb(g)
        chat = pb(first(g, 1, b""))
        name = first(chat, 19)
        for idx in (i for v in g.get(2, []) for i in (packed(v) if isinstance(v, bytes) else [v])):
            models[idx] = name.decode() if name else None
    return models


def conversation(path, since, cwd):
    cid = os.path.basename(path)[:-3]
    db = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    models, last = models_by_step(db), None
    for idx, kind, raw in db.execute("select idx, step_type, metadata from steps order by idx"):
        m = pb(raw or b"")  # CortexStepMetadata{1 created_at{1 seconds}, 4 tool_call, 9 model_usage}
        secs = first(pb(first(m, 1, b"")), 1)
        if secs is None or secs < since.timestamp():
            continue
        if kind == USER_INPUT:
            yield event("user_prompt", iso(secs), "antigravity", cid, cwd=cwd)
        elif kind == PLANNER_RESPONSE and m.get(9):
            u = pb(m[9][0])  # ModelUsageStats{2 input (excl. cache), 3 output (= 9 thinking + 10 response), 4 cache write, 5 cache read}
            if last:
                yield last
            last = event("api_call", iso(secs), "antigravity", cid, cwd=cwd, request_id=f"{cid}:{idx}",
                         model=models.get(idx), provider="google",
                         tokens=make_tokens(input=first(u, 2, 0), output=first(u, 3, 0),
                                            cache_read=first(u, 5, 0), cache_write=first(u, 4, 0),
                                            reasoning=first(u, 9, 0), output_includes_reasoning=True))
        elif m.get(4) and last:
            name = first(pb(m[4][0]), 2)  # ChatToolCall{2 name}
            last["tools"] = sorted(set(last["tools"]) | {name.decode() if name else "?"})
    if last:
        yield last


def read(since, cfg):
    override = (cfg.get("readers", {}).get("paths") or {}).get("antigravity")
    meta_path = os.path.join(root(cfg, "antigravity", override), os.path.basename(META)) if override else META
    try:
        with open(os.path.expanduser(meta_path)) as f:
            meta = json.load(f)["conversations"]
    except (OSError, ValueError, KeyError):
        meta = {}
    dirs = [root(cfg, "antigravity", override)] if override else [os.path.expanduser(d) for d in ROOTS]
    for path in (p for d in dirs for p in glob.glob(os.path.join(d, "*.db"))):
        if not recent(path, since):
            continue
        roots = ((meta.get(os.path.basename(path)[:-3]) or {}).get("summary") or {}).get("WorkspaceURIs") or [None]
        try:
            yield from list(conversation(path, since, roots[0]))  # list(): a parse error drops the whole conversation
        except (sqlite3.Error, ValueError, IndexError, KeyError) as e:
            coverage[path] = f"{type(e).__name__}: {e}"
