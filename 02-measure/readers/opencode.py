"""OpenCode sqlite: ~/.local/share/opencode/opencode.db. Specs R-opencode-* in readers/METHOD.md."""
import collections, os, sqlite3
from common import root, event, iso, make_tokens

ROOT = "~/.local/share/opencode/opencode.db"


def connect(path):
    """R-opencode-ro: read-only and immutable, so a live WAL database is never locked or modified."""
    return sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)


def read(since, cfg):
    path = root(cfg, "opencode", ROOT)
    if not os.path.exists(path):
        return
    db, since_ms = connect(path), int(since.timestamp() * 1000)
    tools = collections.defaultdict(set)
    for mid, name in db.execute("select message_id, json_extract(data, '$.tool') from part "
                                "where time_created >= ? and json_extract(data, '$.type') = 'tool'", (since_ms,)):
        tools[mid].add(name)
    j = lambda f: f"json_extract(m.data, '$.{f}')"
    rows = db.execute(f"select m.id, m.session_id, m.time_created, {j('role')}, {j('modelID')}, {j('providerID')}, "
                      f"{j('cost')}, {j('tokens.input')}, {j('tokens.output')}, {j('tokens.reasoning')}, "
                      f"{j('tokens.cache.read')}, {j('tokens.cache.write')}, {j('time.completed')}, "
                      f"json_extract(m.data, '$.error.name'), coalesce({j('path.cwd')}, s.directory), s.parent_id "
                      "from message m join session s on s.id = m.session_id where m.time_created >= ? "
                      "order by m.time_created", (since_ms,))
    for mid, sid, t, role, model, provider, usd, inp, out, reas, read_, write, done, err, cwd, parent in rows:
        if role == "user":
            yield event("user_prompt", iso(t / 1000), "opencode", sid, cwd=cwd, parent=parent, subagent=parent is not None)
            continue
        if role != "assistant":
            continue
        tokens = make_tokens(input=inp, output=out, cache_read=read_, cache_write=write, reasoning=reas)
        if not any(tokens.values()) and not err:  # R-opencode-empty: aborted/placeholder message, no API call
            continue
        yield event("api_call", iso(t / 1000), "opencode", sid, cwd=cwd, request_id=mid, parent=parent,
                    subagent=parent is not None, model=model, provider=provider, tokens=tokens,
                    reported_total=usd if usd else None,  # R-opencode-cost
                    duration_ms=(done - t) if done and done >= t else None, error=err, tools=tools[mid])
