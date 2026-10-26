"""Config loader shared by all stages. Spec: schemas/AGENTS.md "Config".

    import pathlib, sys  # in <NN-stage>/<component>/<x>.py; numbered dirs aren't importable
    REPO = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir())
    sys.path.insert(0, str(REPO / "02-measure"))
    from schemas.config import load_config, data_dir, connector
    cfg = load_config(args.config)            # --config PATH > $OTM_CONFIG > <repo>/01-deploy/config.json > defaults
    write = connector(SINKS, cfg["analyze"]["sink"], "analyze.sink")
"""
import copy, json, os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo: <repo>/02-measure/schemas/config.py
CONFIG_DEFAULT = os.path.join(ROOT, "01-deploy", "config.json")  # next to 01-deploy/config.example.json
CONFIG_ENV, DATA_ENV = "OTM_CONFIG", "OTM_DATA_DIR"
DEFAULT_DATA_DIR = "~/.local/share/opentokenmini"
HARNESSES = ["claude-code", "codex", "antigravity", "opencode", "pi"]
# null = use the constant at the top of the stage file
DEFAULTS = {
    "data_dir": None,
    "collector": {"sink": "files", "bind": "127.0.0.1", "port": None, "token_env": None, "hash_identity": True},
    "readers": {"enabled": HARNESSES, "paths": {}},
    "analyze": {"source": "files", "sink": "files", "prefer_source": "otel"},
    "impact": {"vcs": "local_git", "repos": [], "read_subjects": False},
    "decide": {"vendor": "jev", "points": ["outlier_explanation", "recommendation"]},
    "mcp": {"source": "files"},
}


# types for keys whose default is null (others must match their default's type)
NULLABLE = {"data_dir": str, "collector.port": int, "collector.token_env": str}


def _type_ok(v, t):
    return isinstance(v, t) and not (isinstance(v, bool) and t is not bool)


def _check_value(key, v, default):
    """Raise ValueError if v cannot replace default at dotted key."""
    want = NULLABLE.get(key) if default is None else type(default)
    if v is None and default is not None:
        raise ValueError(f"config: {key} must be {want.__name__}, got {v!r}")
    if v is not None and want and not _type_ok(v, want):
        raise ValueError(f"config: {key} must be {want.__name__}{' or null' if default is None else ''}, got {v!r}")
    if isinstance(v, list) and not all(isinstance(i, str) for i in v):
        raise ValueError(f"config: {key} must be a list of strings")


def _merge(base, over, at=""):
    for k, v in over.items():
        if k.startswith("_"):  # comment, at any depth
            continue
        if k not in base:
            raise ValueError(f"config: unknown key {at}{k}")
        _check_value(at + k, v, base[k])
        if isinstance(base[k], dict) and k != "paths":
            _merge(base[k], v, f"{at}{k}.")
        else:
            base[k] = v
    return base


def _check_harnesses(cfg):
    r = cfg["readers"]
    bad = sorted(set(r["enabled"]) - set(HARNESSES)) + sorted(set(r["paths"]) - set(HARNESSES))
    if bad:
        raise ValueError(f"config: readers unknown harness {bad}, known {HARNESSES}")
    if not all(isinstance(v, str) for v in r["paths"].values()):
        raise ValueError("config: readers.paths values must be strings")
    return cfg


def load_config(path=None):
    """Defaults deep-merged with the first existing file of: path, $OTM_CONFIG, <repo>/01-deploy/config.json.
    An explicit path or $OTM_CONFIG that does not exist is an error; a missing repo 01-deploy/config.json is not."""
    explicit = path or os.environ.get(CONFIG_ENV)
    path = explicit or CONFIG_DEFAULT
    cfg = copy.deepcopy(DEFAULTS)
    if not os.path.exists(path):
        if explicit:
            raise FileNotFoundError(f"config: {path} not found")
        return cfg
    with open(path) as f:
        r = _merge(cfg, json.load(f))
    r["readers"]["paths"] = {k: v for k, v in r["readers"]["paths"].items() if not k.startswith("_")}
    return _check_harnesses(r)


def data_dir(cfg):
    """$OTM_DATA_DIR > cfg data_dir > DEFAULT_DATA_DIR; the data root, never inside the repo."""
    d = os.path.abspath(os.path.expanduser(os.environ.get(DATA_ENV) or cfg.get("data_dir") or DEFAULT_DATA_DIR))
    if d == ROOT or d.startswith(ROOT + os.sep):
        raise ValueError(f"config: data dir {d} is inside the repo")
    return d


def connector(registry, name, key):
    """Look up a connector function by name; clear error listing the available ones."""
    if name not in registry:
        raise KeyError(f"config {key}={name!r}: available {sorted(registry)}")
    return registry[name]
