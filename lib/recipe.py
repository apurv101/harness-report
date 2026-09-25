#!/usr/bin/env python3
"""recipe.py — everything run.sh does to a recipe.json: accept one from the analyzer, read fields out of it,
and say how it differs from the last one.

    recipe.py save <analyze.raw.json> <recipe.json> <Dockerfile>   validate the analyzer's output and write both
    recipe.py field <recipe.json> <key> [default]                  print one field
    recipe.py ok <recipe.json>                                     exit 0 if this recipe is usable by this version
    recipe.py hash <recipe.json>                                   the first 16 hex of its sha256 (an image label)
    recipe.py env <recipe.json> <proxy-url>                        NAME=VALUE lines, $PROXY_URL substituted
    recipe.py diff <previous.json> <recipe.json> <out.diff>        a unified diff of the setup fields

`save` is the gate on the analyzer: a dockerfile that is not an overlay (ARG BASE / FROM ${BASE}) is rejected here
and the message goes back to the analyzer as its feedback.  `ok` is the gate on a stored recipe: an older one,
written before the overlay rule, fails it and is re-analyzed.
"""
import difflib, hashlib, json, os, re, sys, tempfile

FIELDS = ("base_image", "dockerfile", "run_command", "check_command", "env", "api_style")


def save(args):
    """Validate the analyzer's structured output, then write recipe.json and the overlay Dockerfile."""
    raw, recipe, dockerfile = args
    d = json.load(open(raw))
    so = d.get("structured_output")
    if not so: sys.exit(f"analyze: no structured output (subtype={d.get('subtype')}, result={str(d.get('result'))[:300]})")
    lines = [l.strip() for l in so["dockerfile"].splitlines() if l.strip() and not l.strip().startswith("#")]
    if not (len(lines) > 1 and re.match(r"ARG\s+BASE(=|\s|$)", lines[0]) and re.match(r"FROM\s+(--platform=\S+\s+)?\$\{?BASE\}?(\s|$)", lines[1])):
        sys.exit("recipe rejected: the dockerfile must begin with 'ARG BASE=<base_image>' then 'FROM ${BASE}' (it is an overlay built on top of an image chosen at build time). It began with:\n" + "\n".join(lines[:3]))
    json.dump(so, open(recipe, "w"), indent=2)
    open(dockerfile, "w").write(so["dockerfile"].rstrip() + "\n")
    print(f"recipe: api={so['api_style']}  base={so['base_image']}  env={' '.join(e['name'] for e in so['env'])}  cost=${d.get('total_cost_usd', 0):.2f}  turns={d.get('num_turns')}")
    print("summary: " + so["summary"].strip().replace("\n", " ")[:600])
    print("run_command: " + so["run_command"].strip())


def field(args):
    """One field of the recipe, or the given default when it is missing or empty."""
    r = json.load(open(args[0]))
    print(r[args[1]] if len(args) < 3 else (r.get(args[1]) or args[2]))


def ok(args):
    """Exit 0 if the recipe has every field this version needs and its dockerfile is an overlay."""
    r = json.load(open(args[0]))
    ls = [l.strip() for l in r.get("dockerfile", "").splitlines() if l.strip() and not l.strip().startswith("#")]
    sys.exit(0 if all(k in r for k in FIELDS) and len(ls) > 1 and re.match(r"ARG\s+BASE", ls[0]) and "BASE" in ls[1] else 1)


def digest(args):
    """The recipe's identity, as an image label: two runs share an overlay only if this matches."""
    print(hashlib.sha256(open(args[0], "rb").read()).hexdigest()[:16])


def env(args):
    """The recipe's env as NAME=VALUE lines for `docker run -e`, with $PROXY_URL pointing at this run's proxy."""
    recipe, proxy = args
    for e in json.load(open(recipe))["env"]:
        print(e["name"] + "=" + e["value"].replace("$PROXY_URL", proxy).replace("${PROXY_URL}", proxy))


def diff(args):
    """How this recipe differs from the one before it, so a changed result can be traced to a changed sandbox."""
    prev, new, out = args
    a, b = json.load(open(prev)), json.load(open(new))
    parts = []
    for k in sorted(set(a) | set(b)):
        x, y = a.get(k), b.get(k)
        if x == y or k in ("summary", "notes"): continue   # prose, not setup
        x = x if isinstance(x, str) else json.dumps(x, indent=1); y = y if isinstance(y, str) else json.dumps(y, indent=1)
        x, y = (x or "").rstrip("\n") + "\n", (y or "").rstrip("\n") + "\n"
        parts.append("".join(difflib.unified_diff(x.splitlines(True), y.splitlines(True), f"previous/{k}", f"this/{k}")))
    if parts: open(out, "w").write("\n".join(p.rstrip("\n") + "\n" for p in parts))
    print(f"recipe vs previous: {'changed: ' + ', '.join(p.split(chr(10))[0].split('/')[-1] for p in parts) if parts else 'unchanged'}")


def cache(args):
    source, destination = args
    with tempfile.NamedTemporaryFile(dir=os.path.dirname(destination), delete=False) as f:
        f.write(open(source, "rb").read())
    os.replace(f.name, destination)


if __name__ == "__main__":
    {"save": save, "field": field, "ok": ok, "hash": digest, "env": env, "diff": diff, "cache": cache}[sys.argv[1]](sys.argv[2:])
