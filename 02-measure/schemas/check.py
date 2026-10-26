#!/usr/bin/env python3
"""Validate an OpenTokenMini file (.json or .jsonl) against a schema in this directory.

python3 02-measure/schemas/check.py FILE [SCHEMA]   SCHEMA = name (event, session, ...) or path; inferred from FILE if omitted.
Exit 0 if valid, 1 with one error per line otherwise. Library: validate(obj, name), check_file(path, name).
Supports the JSON Schema subset used here: type, enum, const, required, properties, additionalProperties,
items, minItems/maxItems, minimum/maximum, minLength, pattern, anyOf, allOf, $ref (local or file#/pointer).
Semantic rules on top: C-sum, S-event-kind, S-decision-choice, S-session-order, S-raw-payload (schemas/METHOD.md).
const is type-strict (1.0 and True do not match 1).
"""
import json, os, re, sys
from datetime import datetime
try:  # imported as schemas.check, or run as schemas/check.py
    from schemas.cost import COST_PARTS, CACHE_TTL as TTL_KEYS  # C-sum, C-cache-ttl
except ImportError:
    from cost import COST_PARTS, CACHE_TTL as TTL_KEYS

HERE = os.path.dirname(os.path.abspath(__file__))
SUM_TOL = 1e-6  # C-sum: |input + output + cache_read + cache_write - total| <= SUM_TOL USD
MAX_ERRORS = 50  # per file, printed
ZERO_KINDS = ("user_prompt", "tool_decision")  # S-event-kind: all-zero tokens and cost
TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}
# file name -> schema name, first match wins
INFER = [(r"(^|/)otel/[a-z]+-\d{4}-\d{2}-\d{2}\.jsonl$", "raw"), (r"(^|/)events/[^/]+\.jsonl$", "event"),
         (r"sessions[^/]*\.jsonl$", "session"), (r"analysis[^/]*\.json$", "analysis"),
         (r"impact_summary[^/]*\.json$", "impact_summary"), (r"impact[^/]*\.jsonl$", "impact"),
         (r"decisions[^/]*\.jsonl$", "decision"), (r"deployments[^/]*\.jsonl$", "deployment"),
         (r"issues[^/]*\.jsonl$", "issue"), (r"events[^/]*\.jsonl$", "event")]
_cache = {}


def load_schema(name):
    path = name if name.endswith(".json") else os.path.join(HERE, f"{name}.schema.json")
    path = os.path.abspath(path)
    if path not in _cache:
        with open(path) as f:
            _cache[path] = json.load(f)
    return path, _cache[path]


def _resolve(ref, base):
    file, _, pointer = ref.partition("#")
    path, doc = load_schema(os.path.join(os.path.dirname(base), file)) if file else (base, _cache[base])
    for part in [p for p in pointer.split("/") if p]:
        doc = doc[part]
    return doc, path


def _type_ok(x, t):
    if t == "integer":
        return isinstance(x, int) and not isinstance(x, bool)
    if t == "number":
        return isinstance(x, (int, float)) and not isinstance(x, bool)
    return isinstance(x, TYPES[t])


def _check(x, s, base, at, errs):
    if "$ref" in s:
        s2, base2 = _resolve(s["$ref"], base)
        _check(x, s2, base2, at, errs)
    if "type" in s and not _check_type(x, s, at, errs):
        return
    _check_values(x, s, base, at, errs)
    _check_number(x, s, at, errs)
    _check_string(x, s, at, errs)
    _check_object(x, s, base, at, errs)
    _check_array(x, s, base, at, errs)


def _check_type(x, s, at, errs):
    ts = s["type"] if isinstance(s["type"], list) else [s["type"]]
    if any(_type_ok(x, t) for t in ts):
        return True
    errs.append(f"{at}: expected {'|'.join(ts)}, got {type(x).__name__}")
    return False


def _check_values(x, s, base, at, errs):
    """const, enum, anyOf, allOf."""
    if "const" in s and (x != s["const"] or type(x) is not type(s["const"])):
        errs.append(f"{at}: expected {s['const']!r}, got {x!r}")
    if "enum" in s and x not in s["enum"]:
        errs.append(f"{at}: {x!r} not in {s['enum']}")
    if "anyOf" in s and all(_errors(x, sub, base, at) for sub in s["anyOf"]):
        errs.append(f"{at}: matches none of anyOf: " + "; ".join(e for sub in s["anyOf"] for e in _errors(x, sub, base, at)[:2]))
    for sub in s.get("allOf", []):
        _check(x, sub, base, at, errs)


def _check_number(x, s, at, errs):
    if not _type_ok(x, "number"):
        return
    if "minimum" in s and x < s["minimum"]:
        errs.append(f"{at}: {x} < {s['minimum']}")
    if "maximum" in s and x > s["maximum"]:
        errs.append(f"{at}: {x} > {s['maximum']}")


def _check_string(x, s, at, errs):
    if not isinstance(x, str):
        return
    if len(x) < s.get("minLength", 0):
        errs.append(f"{at}: shorter than {s['minLength']}")
    if "pattern" in s and not re.search(s["pattern"], x):
        errs.append(f"{at}: {x!r} does not match {s['pattern']}")


def _check_object(x, s, base, at, errs):
    if not isinstance(x, dict):
        return
    errs += [f"{at}: missing {k}" for k in s.get("required", []) if k not in x]
    props, extra = s.get("properties", {}), s.get("additionalProperties", True)
    for k, v in x.items():
        sub = props.get(k, extra)
        if sub is False and k not in props:
            errs.append(f"{at}: unexpected key {k}")
        elif isinstance(sub, dict):
            _check(v, sub, base, f"{at}.{k}", errs)


def _check_array(x, s, base, at, errs):
    if not isinstance(x, list):
        return
    if len(x) < s.get("minItems", 0):
        errs.append(f"{at}: fewer than {s['minItems']} items")
    if "maxItems" in s and len(x) > s["maxItems"]:
        errs.append(f"{at}: more than {s['maxItems']} items")
    for i, v in enumerate(x):
        _check(v, s.get("items", {}), base, f"{at}[{i}]", errs)


def _errors(x, s, base, at):
    errs = []
    _check(x, s, base, at, errs)
    return errs


def _cost_sums(x, at, errs):
    """C-sum: every cost object's parts add up to its total."""
    if isinstance(x, dict):
        if "total" in x and all(isinstance(x.get(p), (int, float)) for p in COST_PARTS) and isinstance(x["total"], (int, float)):
            diff = sum(x[p] for p in COST_PARTS) - x["total"]
            if abs(diff) > SUM_TOL:
                errs.append(f"{at}: C-sum cost parts sum to total {x['total']} off by {diff:.3g}")
        for k, v in x.items():
            _cost_sums(v, f"{at}.{k}", errs)
    elif isinstance(x, list):
        for i, v in enumerate(x):
            _cost_sums(v, f"{at}[{i}]", errs)


def _cache_ttl(x, at, errs):
    """C-cache-ttl: wherever a tokens object has cache_write_5m/1h, their sum <= cache_write."""
    if isinstance(x, dict):
        if isinstance(x.get("cache_write"), int) and any(isinstance(x.get(k), int) for k in TTL_KEYS):
            if sum(x.get(k, 0) for k in TTL_KEYS if isinstance(x.get(k), int)) > x["cache_write"]:
                errs.append(f"{at}: C-cache-ttl cache_write_5m + cache_write_1h > cache_write")
        for k, v in x.items():
            _cache_ttl(v, f"{at}.{k}", errs)
    elif isinstance(x, list):
        for i, v in enumerate(x):
            _cache_ttl(v, f"{at}[{i}]", errs)


def _semantic(x, name, at, errs):
    _cost_sums(x, at, errs)
    if not isinstance(x, dict):
        return
    _cache_ttl(x, at, errs)
    rule = RULES.get(name)
    if rule:
        rule(x, at, errs)


def _event_kind(x, at, errs):  # S-event-kind
    kind = x.get("kind")
    has_decision = x.get("decision") is not None or x.get("decision_source") is not None
    if kind != "tool_decision" and has_decision:
        errs.append(f"{at}: S-event-kind decision/decision_source only on tool_decision")
    if kind == "tool_decision" and (x.get("tool") is None or x.get("decision") is None):
        errs.append(f"{at}: S-event-kind tool_decision needs tool and decision")
    if kind not in ZERO_KINDS:
        return
    for f in ("tokens", "cost"):
        if isinstance(x.get(f), dict) and any(x[f].values()):
            errs.append(f"{at}: S-event-kind {kind} carries no {f}")


def _decision_choice(x, at, errs):  # S-decision-choice
    opts, probs, choice = x.get("options", {}), x.get("probabilities", {}), x.get("choice")
    if not (isinstance(opts, dict) and isinstance(probs, dict)):
        return
    unknown = set(probs) - set(opts)
    if unknown:
        errs.append(f"{at}: S-decision-choice probabilities for unknown options {sorted(unknown)}")
    if choice != "unsure" and choice not in opts:
        errs.append(f"{at}: S-decision-choice {choice!r} is neither an option nor 'unsure'")


def _session_order(x, at, errs):  # S-session-order
    start, end = _dt(x.get("start")), _dt(x.get("end"))
    if start and end and end < start:
        errs.append(f"{at}: S-session-order end before start")


def _raw_payload(x, at, errs):  # S-raw-payload (v1 only)
    if "v" in x and sum(k in x for k in ("data", "data_b64", "undecoded")) != 1:
        errs.append(f"{at}: S-raw-payload v1 needs exactly one of data, data_b64, undecoded")


RULES = {"event": _event_kind, "decision": _decision_choice, "session": _session_order, "raw": _raw_payload}


def _dt(v):
    """Aware datetime from a schema ts string, None if not parseable (the pattern check reports it)."""
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")) if isinstance(v, str) else None
    except ValueError:
        return None


def validate(obj, name, at="$"):
    """Return a list of error strings (empty = valid)."""
    path, schema = load_schema(name)
    errs = _errors(obj, schema, path, at)
    _semantic(obj, os.path.basename(path).split(".")[0], at, errs)
    return errs


def infer(path):
    p = path.replace(os.sep, "/")
    return next((n for rx, n in INFER if re.search(rx, p)), None)


def check_file(path, name=None):
    name = name or infer(path)
    if not name:
        return [f"{path}: cannot infer schema, pass it explicitly"]
    errs = []
    with open(path) as f:
        if path.endswith(".jsonl"):
            for i, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    errs += validate(json.loads(line), name, f"line {i}")
                except ValueError as e:
                    errs.append(f"line {i}: invalid JSON: {e}")
        else:
            try:
                errs += validate(json.load(f), name)
            except ValueError as e:
                errs.append(f"invalid JSON: {e}")
    return errs


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__.split("\n\n")[1])
    errors = check_file(sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else None)
    for e in errors[:MAX_ERRORS]:
        print(e)
    if len(errors) > MAX_ERRORS:
        print(f"... {len(errors) - MAX_ERRORS} more")
    print(f"{sys.argv[1]}: {'ok' if not errors else f'{len(errors)} errors'}", file=sys.stderr)
    sys.exit(1 if errors else 0)
