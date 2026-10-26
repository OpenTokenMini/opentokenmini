"""Fake gh for pipeline tests: serves gh.json ({today} = current UTC date), logs argv to $FAKE_GH_LOG. No network.
$FAKE_GH_AUTH=0 makes `gh auth status` fail (not authenticated)."""
import json, os, sys
from datetime import datetime, timezone

args = sys.argv[1:]
if os.environ.get("FAKE_GH_LOG"):
    with open(os.environ["FAKE_GH_LOG"], "a") as f:
        f.write(" ".join(args[:2]) + "\n")
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "gh.json")) as f:
    gh = json.loads(f.read().replace("{today}", datetime.now(timezone.utc).strftime("%Y-%m-%d")))
if args[:2] == ["auth", "status"]:
    sys.exit(0 if os.environ.get("FAKE_GH_AUTH", "1") == "1" else 1)
if args[:2] == ["run", "list"]:
    print(json.dumps(gh["runs"]))
elif args[:2] == ["run", "view"]:
    print(json.dumps(gh["jobs"][args[2]]))
elif args[:2] == ["api", "graphql"]:
    q = next(a for a in args if a.startswith("query="))
    print(json.dumps(gh["pullRequests" if "pullRequests(" in q else "issues"]))
else:
    sys.exit(f"fake gh: unsupported {args}")
