# decide

Asks a decision model to explain outliers, judge recommendations and confirm window commit links. Never edits analyze or impact output.

Input (data dir or `--in DIR`): `analysis.json` (required), `sessions.jsonl`, `impact.jsonl`. Output (`--out DIR`, default data dir): `decisions.jsonl` (appended; also the cache), `analysis.decided.json`. Data sent to the vendor: the numeric states in METHOD.md D-state, nothing else.

```
python3 06-optional/decide/decide.py --dry-run                 # how many questions would be asked
python3 06-optional/decide/decide.py [--harness ID] [--max-calls N] [--config PATH]
python3 06-optional/decide/decide.py --ask "state" "question" [option ...]    # one call; no options = yes/no
```

jev needs `TYPESAFE_API_KEY` in the environment. Set `OTM_LEDGER=<file.jsonl>` to append `{agent, n, ts, vendor}` per run (n = questions). Second run with unchanged inputs asks nothing.

## Reconfigure

Config keys (`01-deploy/config.json`): `decide.vendor` (`jev` default, `d1`, `stub`, `llm`), `decide.points` (subset of `outlier_explanation`, `recommendation`; `commit_link` always runs when impact has window candidates). Thresholds are constants at the top of `decide.py`; questions, options and rubrics in `points.json`; recommendation candidates in `analyze/metrics.json` (single source).

Vendors live in `connectors.py`: `VENDORS = {name: ask}` with `ask(state, question, options, kind) -> {option: p}` (`options` = {name: rubric|None}; kind `noul` uses options yes/no). Optional `BATCH[name] = batch(state, {qid: (question, options, kind)}) -> {qid: probs}` for many questions on one state. `MODELS[name]` is recorded in each decision. `d1` posts to `$D1_URL/ask`; `stub` is a deterministic offline fake for tests; `llm` is a placeholder that raises.

Example, a local vendor:

```python
def mine(state, question, options, kind):
    p = post("http://127.0.0.1:7899/score", {"s": state, "q": question, "o": list(options)})["p"]
    return dict(zip(options, p))
VENDORS["mine"] = mine; MODELS["mine"] = "mine-v1"
```
then `{"decide": {"vendor": "mine"}}` in 01-deploy/config.json.

## Adapt, trade-offs, decisions for the human

- Adapt: vendor (hosted jev, local `d1`, or your own connector), which points run (`decide.points`), questions and rubrics in `points.json`, thresholds at the top of `decide.py`.
- Trade-offs: a small decision model is cheap and returns probabilities, but sees only the numeric state; answers below the lead threshold come back "unsure" and go to a person. The hosted vendor receives those numeric states.
- Decisions for the human: whether numeric state may leave the machine (hosted vs local vendor); which decision points to delegate; what to do with "unsure" answers.
