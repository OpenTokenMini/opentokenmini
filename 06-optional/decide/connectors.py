"""Decision vendors: name -> ask(state, question, options, kind) -> {option: p}.
options: {name: rubric|None}; kind: "noul" (options must be yes/no), "choice", "score" (ordered levels).
A vendor may also register a batch function in BATCH: batch(state, {qid: (question, options, kind)}) -> {qid: probs},
used when several questions share one state (one request instead of N)."""
import hashlib, json, os, urllib.request

JEV_URL = os.environ.get("JEV_URL", "https://api.typesafe.ai/v1/systemone")
JEV_KEY_ENV = "TYPESAFE_API_KEY"
JEV_MODEL = "jev-latest"
D1_URL = os.environ.get("D1_URL", "")  # local d1 server base URL, POST /ask
TIMEOUT = 30  # seconds per request
MODELS = {"jev": JEV_MODEL, "d1": "d1", "stub": "stub", "llm": None}  # recorded in decisions.jsonl


def post(url, body, headers=None):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def jev_question(question, options, kind):
    if kind == "noul":
        return {"type": "noul", "instructions": question}
    return {"type": kind, "instructions": question, "criteria": options if kind == "choice" else list(options)}


def jev_probs(answer, options):
    if answer["type"] == "noul":
        return {"yes": answer["noul"], "no": 1 - answer["noul"]}
    return dict(zip(options, answer["probabilities"].values()))  # score keys may be relabelled levels


def jev_batch(state, questions):
    key = os.environ.get(JEV_KEY_ENV)
    if not key:
        raise RuntimeError(f"jev: ${JEV_KEY_ENV} not set")
    body = {"state": state, "model": JEV_MODEL, "questions": {q: jev_question(*v) for q, v in questions.items()}}
    answers = post(JEV_URL, body, {"Authorization": f"Bearer {key}"})["answers"]
    return {q: jev_probs(answers[q], list(v[1])) for q, v in questions.items()}


def jev(state, question, options, kind):
    return jev_batch(state, {"q": (question, options, kind)})["q"]


def d1(state, question, options, kind):
    if not D1_URL:
        raise RuntimeError("d1: set D1_URL to the local d1 server")
    opts = [[k, v] for k, v in options.items()] if kind != "noul" else []
    a = post(D1_URL.rstrip("/") + "/ask", {"state": state, "q": question, "type": kind, "opts": opts})["answer"]
    return jev_probs(a, list(options))  # same answer shape as jev (public decide.py contract; unverified, d1 not running)


def stub(state, question, options, kind):
    """Offline, deterministic: probabilities from a hash of the input. For tests and dry runs only."""
    w = [int(hashlib.sha256(f"{state}\0{question}\0{o}".encode()).hexdigest()[:8], 16) + 1 for o in options]
    return {o: x / sum(w) for o, x in zip(options, w)}


def llm(state, question, options, kind):
    raise NotImplementedError("llm: placeholder; ask a generative model to answer with one option, return {option: p}")


VENDORS = {"jev": jev, "d1": d1, "stub": stub, "llm": llm}
BATCH = {"jev": jev_batch}
