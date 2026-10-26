#!/usr/bin/env python3
"""Runs the decision points (METHOD.md D-*) over analysis.json, sessions.jsonl and impact.jsonl.
Writes decisions.jsonl (also the cache: never asks the same (point, state_sha) twice) and
analysis.decided.json (a copy of analysis.json with decisions applied; analysis.json is never edited).
Usage: python3 06-optional/decide/decide.py [--in DIR] [--out DIR] [--harness ID] [--config PATH] [--max-calls N] [--dry-run]
       python3 06-optional/decide/decide.py --ask STATE QUESTION [OPTION ...]   (no options = yes/no)"""
import argparse, copy, datetime, hashlib, importlib.util, json, os, sys

sys.dont_write_bytecode = True
import pathlib  # numbered stage dirs aren't importable: find the repo, put 02-measure/ on sys.path
REPO = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir())
sys.path.insert(0, str(REPO / "02-measure"))
from schemas.config import load_config, data_dir, connector
from schemas.check import validate


def _load(name):  # by path, under a unique module name: every stage has a connectors.py
    spec = importlib.util.spec_from_file_location("decide_" + name, os.path.join(os.path.dirname(os.path.abspath(__file__)), name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


connectors, dp = _load("connectors"), _load("decision_points")
VENDORS, BATCH, MODELS = connectors.VENDORS, connectors.BATCH, connectors.MODELS

MIN_LEAD = 0.2  # D-pick: top option must beat the runner-up by this much, else "unsure"
SUGGEST_P = 0.7  # D-recommendation: p_yes >= this -> "suggest"
SKIP_P = 0.3  # D-recommendation: p_yes <= this -> "skip"; between -> "unsure"
MAX_CALLS = 1000  # questions per run; the rest wait for the next run (cache keeps what was asked)
BATCH_SIZE = 16  # questions per request for vendors with a batch function
LEDGER_ENV = "OTM_LEDGER"  # jsonl that gets one line per agent per run: {agent, n, ts, vendor}
POINTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "points.json")
ALWAYS = ("commit_link",)  # D-commit-link runs whenever impact.jsonl has window candidates (impact needs it)


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def state_sha(it):  # D-cache
    raw = json.dumps([it["state"], it["question"], it["options"], it["kind"]], sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def pick(probs):  # D-pick
    ranked = sorted(probs.items(), key=lambda kv: (-kv[1], kv[0]))
    if not ranked:
        return "unsure"
    lead = ranked[0][1] - (ranked[1][1] if len(ranked) > 1 else 0)
    return ranked[0][0] if lead >= MIN_LEAD else "unsure"


def verdict(p_yes):  # D-recommendation
    return "suggest" if p_yes >= SUGGEST_P else "skip" if p_yes <= SKIP_P else "unsure"


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def ask_all(items, vendor, max_calls):
    """Asks each item once; batches items that share a state. Returns {index: probs}, counts per agent."""
    ask, batch = VENDORS[vendor], BATCH.get(vendor)
    todo, out, used = list(enumerate(items))[:max_calls], {}, {}
    groups, step = {}, BATCH_SIZE if batch else 1
    for i, it in todo:
        groups.setdefault(it["state"], []).append(i)
    try:
        for state, idx in groups.items():
            for k in range(0, len(idx), step):
                chunk = idx[k:k + step]
                if batch:
                    res = batch(state, {str(i): (items[i]["question"], items[i]["options"], items[i]["kind"]) for i in chunk})
                    out.update({int(q): p for q, p in res.items()})
                else:
                    out[chunk[0]] = ask(state, items[chunk[0]]["question"], items[chunk[0]]["options"], items[chunk[0]]["kind"])
                for i in chunk:
                    used[items[i]["agent"]] = used.get(items[i]["agent"], 0) + 1
    except Exception as e:  # stop at the first vendor failure; what was answered is kept
        print(f"decide: {vendor} failed after {len(out)} answers: {e}", file=sys.stderr)
    return out, used


def ledger(used, vendor):
    path = os.environ.get(LEDGER_ENV)
    if not path or vendor == "stub":
        return
    with open(path, "a") as f:
        for agent, n in used.items():
            f.write(json.dumps({"agent": agent, "n": n, "ts": now(), "vendor": vendor}) + "\n")


def run(src, out, cfg, harness=None, max_calls=MAX_CALLS, dry=False):
    vendor = cfg["decide"]["vendor"]
    connector(VENDORS, vendor, "decide.vendor")
    analysis, targets = collect(src, set(cfg["decide"]["points"]) | set(ALWAYS), harness)
    dec_path = os.path.join(out, "decisions.jsonl")
    cache = {(d["point"], d["state_sha"]): d for d in read_jsonl(dec_path)}
    new = to_ask(targets, cache)
    print(f"decide: {len(targets)} items, {len(targets) - len(new)} cached, {len(new)} to ask ({vendor})", file=sys.stderr)
    if dry:
        return {"items": len(targets), "to_ask": len(new)}

    answers, used = ask_all(new, vendor, max_calls)
    ledger(used, vendor)
    os.makedirs(out, exist_ok=True)
    record(dec_path, new, answers, vendor, cache)
    write_decided(out, apply(analysis, targets, cache))
    keys = [(it["point"], it["state_sha"]) for _, it in targets]
    unsure = sum(1 for k in keys if cache.get(k, {}).get("choice") == "unsure")
    unsure_asked = sum(1 for i in answers if cache[(new[i]["point"], new[i]["state_sha"])]["choice"] == "unsure")
    missing = sum(1 for k in keys if k not in cache)
    print(f"decide: asked {sum(used.values())} (unsure {unsure_asked}), all {len(keys)} items (unsure {unsure}), "
          f"unanswered {missing}", file=sys.stderr)
    return {"items": len(targets), "asked": sum(used.values()), "unsure": unsure, "unsure_asked": unsure_asked,
            "unanswered": missing}


def collect(src, enabled, harness):
    """Reads the inputs and builds the (key, item) targets for the enabled decision points."""
    points = json.load(open(POINTS))
    if "intent" in enabled:
        raise SystemExit("decide: intent needs prompt text, which v002 events never carry (D-intent)")
    analysis = json.load(open(os.path.join(src, "analysis.json")))
    sessions = read_jsonl(os.path.join(src, "sessions.jsonl"))
    impact = read_jsonl(os.path.join(src, "impact.jsonl"))
    by_sid = {s["session_id"]: s for s in sessions}
    targets = []
    if "outlier_explanation" in enabled:
        targets += [(("o", k), it) for k, it in dp.outliers(analysis, by_sid, points["outlier_explanation"])]
    if "recommendation" in enabled:
        targets += [(("r", k), it) for k, it in dp.recommendations(analysis, sessions, points["recommendation"], harness)]
    targets += [(("c", k), it) for k, it in dp.commit_links(impact, by_sid, points["commit_link"])]
    if harness:
        targets = [(k, it) for k, it in targets if it["harness"] in (harness, None)]
    return analysis, targets


def to_ask(targets, cache):
    """D-cache: stamps state_sha on every item; returns the uncached ones, one per (point, state_sha)."""
    for _, it in targets:
        it["state_sha"] = state_sha(it)
    new = [it for _, it in targets if (it["point"], it["state_sha"]) not in cache]
    return list({(it["point"], it["state_sha"]): it for it in new}.values())


def record(dec_path, new, answers, vendor, cache):
    """Appends one validated decision per answer to decisions.jsonl and to the cache."""
    with open(dec_path, "a") as f:
        for i, probs in answers.items():
            d = decision(new[i], probs, vendor)
            f.write(json.dumps(d) + "\n")
            cache[(d["point"], d["state_sha"])] = d


def decision(it, probs, vendor):
    d = {"v": 1, "ts": now(), "point": it["point"], "subject": it["subject"], "state_sha": it["state_sha"],
         "question": it["question"], "options": it["options"],
         "probabilities": {k: round(float(v), 4) for k, v in probs.items() if k in it["options"]},
         "vendor": vendor, "model": MODELS.get(vendor)}
    d["choice"] = pick(d["probabilities"])
    errs = validate(d, "decision")
    if errs:
        raise SystemExit(f"decide: invalid decision {errs[:3]}")
    return d


def write_decided(out, decided):
    errs = validate(decided, "analysis")
    if errs:
        raise SystemExit(f"decide: invalid analysis.decided.json {errs[:3]}")
    with open(os.path.join(out, "analysis.decided.json"), "w") as f:
        json.dump(decided, f, indent=1)


def apply(analysis, targets, cache):
    """D-apply: outliers[i].decision, recommendations p_yes/verdict (catalog candidates appended)."""
    a = copy.deepcopy(analysis)
    recs = {r["id"]: r for r in a.setdefault("recommendations", [])}
    for (kind, key), it in targets:
        d = cache.get((it["point"], it["state_sha"]))
        if kind == "o" and d:
            a["outliers"][key]["decision"] = {"choice": d["choice"], "probabilities": d["probabilities"],
                                              "state_sha": d["state_sha"], "vendor": d["vendor"]}
        elif kind == "r":
            r = recs.get(key[0])
            if r is None:
                ev = [{"metric": f"cost_share.{k}", "value": v} for k, v in it["facts"]["cost_mix"].items()]
                r = {"id": key[0], "candidate": key[1], "harness": key[2], "evidence": ev, "p_yes": None, "verdict": None}
                recs[key[0]] = r
                a["recommendations"].append(r)
            if d:
                r["p_yes"] = d["probabilities"].get("yes")
                r["verdict"] = verdict(r["p_yes"]) if r["p_yes"] is not None else None
    return a


def decide(state, question, options=None, kind="choice", vendor="jev"):
    """One-shot (public decide.py interface). options: list or {name: rubric}; none = yes/no."""
    if not options:
        options, kind = {"yes": None, "no": None}, "noul"
    opts = options if isinstance(options, dict) else {o: None for o in options}
    return VENDORS[vendor](state, question, opts, kind)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--in", dest="src", help="dir with analysis.json, sessions.jsonl, impact.jsonl (default: data dir)")
    ap.add_argument("--out", help="dir for decisions.jsonl and analysis.decided.json (default: data dir)")
    ap.add_argument("--harness", help="only items about this harness id")
    ap.add_argument("--config")
    ap.add_argument("--max-calls", type=int, default=MAX_CALLS)
    ap.add_argument("--dry-run", action="store_true", help="count items to ask, call nothing")
    ap.add_argument("--ask", nargs="+", metavar="ARG", help="STATE QUESTION [OPTION ...]: one call, print probabilities")
    a = ap.parse_args()
    cfg = load_config(a.config)
    if a.ask:
        if len(a.ask) < 2:
            ap.error("--ask needs STATE QUESTION")
        p = decide(a.ask[0], a.ask[1], a.ask[2:] or None, vendor=cfg["decide"]["vendor"])
        ledger({"decide": 1}, cfg["decide"]["vendor"])
        print(json.dumps(p, indent=1))
        return
    d = data_dir(cfg)
    print(json.dumps(run(a.src or d, a.out or d, cfg, a.harness, a.max_calls, a.dry_run)))


if __name__ == "__main__":
    main()
