"""Per-token-type cost, shared by readers and normalize. Specs C-* in schemas/METHOD.md.

    from schemas.cost import load_prices, make_tokens, event_cost, worst_basis
    tokens = make_tokens(input=1000, output=250, reasoning=50, cache_read=10000, cache_write=2000, output_includes_reasoning=True)
    cost, basis = event_cost(tokens, "claude-sonnet-4", load_prices())
"""
import json, os

PRICES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prices.json")
PER_TOKENS = 1_000_000  # prices.json is USD per million tokens
TOKEN_TYPES = ("input", "output", "cache_read", "cache_write", "reasoning")
COST_PARTS = ("input", "output", "cache_read", "cache_write")
CACHE_TTL = ("cache_write_5m", "cache_write_1h")  # C-cache-ttl: optional subsets of cache_write, same names in prices.json
BASIS_ORDER = ("reported", "reported_total_allocated", "list_price", "unknown")  # C-basis-worst, best first


def load_prices(path=PRICES_PATH):
    with open(path) as f:
        return json.load(f)  # insertion order kept: first substring match wins (C-price-match)


def price_for(model, prices):
    """C-price-match: first key that is a substring of the lowercased model id, else None (no default)."""
    m = (model or "").lower()
    return next((p for k, p in prices.items() if k.lower() in m), None) if m else None


def make_tokens(input=0, output=0, cache_read=0, cache_write=0, reasoning=0,
                input_includes_cache=False, output_includes_reasoning=False, cache_write_5m=None, cache_write_1h=None):
    """C-tokens: disjoint ints >= 0. Pass the harness's raw counts and say which ones are inclusive.
    C-cache-ttl: pass cache_write_5m/1h when the harness splits writes by TTL; keys appear only if given,
    and cache_write is raised to their sum if smaller."""
    t = {k: int(v or 0) for k, v in zip(TOKEN_TYPES, (input, output, cache_read, cache_write, reasoning))}
    ttl = {k: max(0, int(v or 0)) for k, v in zip(CACHE_TTL, (cache_write_5m, cache_write_1h)) if v is not None}
    t["cache_write"] = max(t["cache_write"], sum(ttl.values()))
    if input_includes_cache:
        t["input"] -= t["cache_read"] + t["cache_write"]
    if output_includes_reasoning:
        t["output"] -= t["reasoning"]
    return {**{k: max(0, v) for k, v in t.items()}, **ttl}


def _with_total(parts):
    c = {k: float(parts.get(k) or 0) for k in COST_PARTS}
    c["total"] = sum(c.values())
    return c


def list_cost(tokens, price):
    """C-list: tokens x USD/Mtok per type; reasoning at the output rate, folded into output."""
    return _with_total({"input": tokens["input"] * price["input"] / PER_TOKENS,
                        "output": (tokens["output"] + tokens["reasoning"]) * price["output"] / PER_TOKENS,
                        "cache_read": tokens["cache_read"] * price["cache_read"] / PER_TOKENS,
                        "cache_write": _cache_write_cost(tokens, price)})


def _cache_write_cost(tokens, price):
    """C-cache-ttl: TTL-split writes at their own rate (fallback cache_write), the unsplit rest at cache_write."""
    split = {k: tokens.get(k, 0) for k in CACHE_TTL}
    rest = max(0, tokens["cache_write"] - sum(split.values()))
    return (rest * price["cache_write"] + sum(n * price.get(k, price["cache_write"]) for k, n in split.items())) / PER_TOKENS


def allocate(total, tokens, price):
    """C-allocate: split a reported total by list-cost shares, else token shares, else all to input."""
    w = list_cost(tokens, price) if price else None
    if not w or w["total"] <= 0:
        w = {"input": tokens["input"], "output": tokens["output"] + tokens["reasoning"],
             "cache_read": tokens["cache_read"], "cache_write": tokens["cache_write"]}
    s = sum(w[k] for k in COST_PARTS)
    parts = {k: total * w[k] / s for k in COST_PARTS} if s > 0 else {"input": total}
    c = _with_total(parts)
    c["total"] = float(total)  # reported total is authoritative; parts differ by float rounding only
    return c


def event_cost(tokens, model, prices, reported=None, reported_total=None):
    """C-cost: returns (cost{input,output,cache_read,cache_write,total}, cost_basis).
    reported: per-type USD dict from the harness (reasoning already inside output); reported_total: USD float."""
    if reported is not None:
        return _with_total(reported), "reported"
    price = price_for(model, prices)
    if reported_total is not None:
        return allocate(reported_total, tokens, price), "reported_total_allocated"
    if price:
        return list_cost(tokens, price), "list_price"
    return _with_total({}), "unknown"


def worst_basis(bases):
    """C-basis-worst: the latest in BASIS_ORDER among bases; 'unknown' if empty."""
    bases = list(bases)
    return max(bases, key=BASIS_ORDER.index) if bases else "unknown"


def zero_tokens():
    return dict.fromkeys(TOKEN_TYPES, 0)


def zero_cost():
    return _with_total({})
