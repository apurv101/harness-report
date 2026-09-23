#!/usr/bin/env python3
"""serve.py — a read-only web UI for the runs/ folder.  No dependencies beyond python3.

    python3 ui/serve.py                 # serves ../runs on http://localhost:8788
    python3 ui/serve.py --port 9000 --runs /path/to/runs

URLs
    /                              list of every run
    /<run-id>                      one run, everything in its folder (runs/<run-id>/)
    /api/runs                      JSON list of runs (summary of each run.json)
    /api/run/<run-id>              JSON bundle: run.json, task, command, recipe, calls[], logs, files[]
    /raw/<run-id>/<file>           a file from the run folder as-is

Every run is one folder runs/<run-id>/; its run.json says what harness (harness.name/repo/commit), what task
(kind prompt|harbor, task.name/taskset, prompt) and what model it ran, plus rc/seconds/reward/calls once finished.
"""
import argparse, json, os, sys
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import unquote

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, "index.html")
RUNS = os.path.abspath(os.path.join(HERE, "..", "runs"))

TEXT_FILES = ("task.txt", "command.sh", "stdout.log", "stderr.log", "proxy.log")   # inlined into the bundle
CORE = TEXT_FILES + ("run.json", "recipe.json", "calls.jsonl")                     # everything else is "other"


def read(path, default=None):
    try:
        with open(path, encoding="utf-8", errors="replace") as f: return f.read()
    except OSError: return default


def load_json(path):
    s = read(path)
    if s is None: return None
    try: return json.loads(s)
    except ValueError: return {"_parse_error": True, "_raw": s}


def run_dirs():
    """Every runs/<run-id> directory, newest first (run ids start with a timestamp)."""
    if not os.path.isdir(RUNS): return []
    return [rid for rid in sorted(os.listdir(RUNS), reverse=True) if os.path.isdir(os.path.join(RUNS, rid)) and not rid.startswith(".")]


def find_run(rid):
    d = os.path.join(RUNS, rid)
    return d if rid and "/" not in rid and rid not in (".", "..") and os.path.isdir(d) else None


def summary(rid):
    """The run's run.json as written by run.sh (origin half before the run, result half merged in after), plus
    `run` (the folder name), `has_run_json`, and `calls` counted from calls.jsonl when the run has not finished."""
    d = os.path.join(RUNS, rid)
    rj = load_json(os.path.join(d, "run.json")) or {}
    out = {"run": rid, "has_run_json": bool(rj), **rj}
    if out.get("calls") is None:
        out["calls"] = sum(1 for l in read(os.path.join(d, "calls.jsonl"), "").splitlines() if l.strip())
    return out


def bundle(d):
    rid = os.path.basename(d)
    calls, bad = [], 0
    for line in (read(os.path.join(d, "calls.jsonl"), "")).splitlines():
        if not line.strip(): continue
        try: calls.append(json.loads(line))
        except ValueError: bad += 1
    files = []
    for root, _, fs in os.walk(d):
        for f in sorted(fs):
            p = os.path.join(root, f); rel = os.path.relpath(p, d)
            files.append({"name": rel, "bytes": os.path.getsize(p), "core": rel in CORE})
    files.sort(key=lambda x: x["name"])
    verifier = {k: read(os.path.join(d, "verifier", k)) for k in ("stdout.log", "stderr.log", "reward.txt")} if os.path.isdir(os.path.join(d, "verifier")) else None
    return {"run": rid, "run_json": summary(rid),
            "recipe": load_json(os.path.join(d, "recipe.json")),
            "calls": calls, "calls_unparsed": bad,
            **{k.split(".")[0]: read(os.path.join(d, k)) for k in TEXT_FILES},
            "verifier": verifier, "files": files}


class H(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *a): sys.stderr.write("%s %s\n" % (self.address_string(), fmt % a))

    def send(self, code, body, ctype):
        if isinstance(body, str): body = body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)

    def json(self, code, obj): self.send(code, json.dumps(obj), "application/json")

    def do_GET(self):
        parts = [unquote(p) for p in self.path.split("?")[0].strip("/").split("/") if p]
        if parts[:1] == ["api"]:
            if parts[1:] == ["runs"]: return self.json(200, [summary(r) for r in run_dirs()])
            if parts[1:2] == ["run"] and len(parts) == 3:
                d = find_run(parts[2])
                return self.json(200, bundle(d)) if d else self.json(404, {"error": "no such run"})
            return self.json(404, {"error": "no such api route"})
        if parts[:1] == ["raw"] and len(parts) >= 3:
            d = find_run(parts[1]); p = os.path.realpath(os.path.join(d or "", *parts[2:]))
            if not d or not p.startswith(os.path.realpath(d) + os.sep) or not os.path.isfile(p): return self.send(404, "not found", "text/plain")
            ctype = "application/json" if p.endswith(".json") else "text/plain; charset=utf-8"
            return self.send(200, open(p, "rb").read(), ctype)
        # anything else is the single page; it reads the path itself
        page = read(PAGE)
        return self.send(200, page, "text/html; charset=utf-8") if page else self.send(500, "index.html missing", "text/plain")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=8788); ap.add_argument("--runs", default=RUNS)
    a = ap.parse_args(); RUNS = os.path.abspath(a.runs)
    print(f"runs UI on http://localhost:{a.port}   runs={RUNS}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()
