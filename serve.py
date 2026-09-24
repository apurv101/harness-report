#!/usr/bin/env python3
"""serve.py — the Harness Report site and read-only run API.  No dependencies beyond python3.

    npm --prefix web install && npm --prefix web run build     # the frontend, once
    python3 serve.py                 # serves web/dist and runs/ on http://localhost:8789
    python3 serve.py --port 9000 --runs /path/to/runs --dist /path/to/dist

URLs
    /                              product landing
    /#runs                        recorded evaluations
    /#runs/<run-id>                run detail
    /<run-id>                      legacy run link (opens the same frontend)
    /api/runs                      JSON list of runs (summary of each run.json)
    /api/run/<run-id>              JSON bundle: run.json, task, command, recipe, calls[], logs, files[]
    /raw/<run-id>/<file>           a file from the run folder as-is
    /auth/github                   start "Sign in with GitHub"; /auth/callback finishes it, /auth/logout ends it
    /api/me                        whether auth is on, and who is signed in
    /api/github/installations      the app installations the signed-in user has
    /api/github/repos?installation=<id>   the repositories one installation grants

The frontend is the React app in web/; `npm --prefix web run build` writes web/dist, and everything under
it is served as-is with index.html as the fallback for the app's own routes.  `npm --prefix web run dev`
serves it on :5173 instead and proxies /api, /auth and /raw back here.

Sign-in is optional: with no GITHUB_CLIENT_ID in the environment nobody can sign in at all.  Either way the
runs are public; only /api/github/* needs the session cookie.  See auth.py for the env it reads.

Every run is one folder runs/<run-id>/; its run.json says what harness (harness.name/repo/commit), what task
(kind prompt|harbor, task.name/taskset, prompt) and what model it ran, plus rc/seconds/reward/calls once finished.
"""
import argparse, json, os, re, sys
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import unquote, parse_qs

import auth

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.abspath(os.path.join(HERE, "web", "dist"))     # the built frontend
RUNS = os.path.abspath(os.path.join(HERE, "runs"))

TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".json": "application/json", ".svg": "image/svg+xml",
         ".txt": "text/plain; charset=utf-8", ".xml": "application/xml", ".ico": "image/x-icon",
         ".png": "image/png", ".webp": "image/webp", ".woff2": "font/woff2", ".map": "application/json"}

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


TEST_LINE = re.compile(r"^(\S+::\S+)\s+(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b", re.M)
TEST_SUMMARY = re.compile(r"^=+ (.*?(?:passed|failed|error)[^=]*?) in [\d.]+s .*=+$", re.M)


FAIL_HEAD = re.compile(r"^_{1,}\s+(\S+)\s+_{1,}$", re.M)


def failure_details(out):
    """pytest's FAILURES section split per test: {test_name: traceback text}."""
    m = re.search(r"^=+ FAILURES =+$\n(.*?)(?=^=+ .* =+$)", out, re.M | re.S)
    if not m: return {}
    parts = FAIL_HEAD.split(m.group(1)); det = {}
    for i in range(1, len(parts) - 1, 2): det[parts[i].split(".")[-1]] = parts[i + 1].strip()
    return det


def test_sources(tdir):
    """{basename: {function name: source}} for every python test file in the task's tests folder."""
    import ast
    src = {}
    for root, _, fs in os.walk(tdir):
        for f in fs:
            if not f.endswith(".py"): continue
            code = read(os.path.join(root, f))
            if code is None: continue
            try: tree = ast.parse(code)
            except SyntaxError: continue
            lines = code.splitlines(); funcs = {}
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                    start = min([node.lineno] + [x.lineno for x in node.decorator_list])
                    funcs[node.name] = "\n".join(lines[start - 1:node.end_lineno])
            src[f] = funcs
    return src


def tests(d, full=False):
    """Per-test results parsed from verifier/stdout.log when the verifier ran pytest -v (the aider_polyglot tasks do):
    passed/failed/total, the failed test names, and pytest's own summary line. None when there is no such output.
    full=True adds `cases`: every test in pytest order with its result, its source from the task's tests folder,
    and its failure traceback."""
    out = read(os.path.join(d, "verifier", "stdout.log"))
    if not out: return None
    found = TEST_LINE.findall(out)
    summ = TEST_SUMMARY.findall(out)
    # pytest aborted before running anything (e.g. a file the agent left behind failed at import): report that, not 0 tests
    aborted = re.search(r"^!+ Interrupted: (.*?) !+$", out, re.M)
    if aborted:
        bad = re.findall(r"^_+ ERROR collecting (\S+) _+$", out, re.M)
        return {"passed": 0, "failed": 0, "total": 0, "failed_names": [], "agent_written": 0, "cases": [] if full else None,
                "aborted": aborted.group(1) + (": " + ", ".join(bad) if bad else ""), "summary": summ[-1] if summ else None}
    if not found and not summ: return None
    by = {}
    for name, res in found: by[name] = res          # a test reported twice keeps its last result
    # Only the task's own test files count: pytest also collects any test files the agent left in the workdir.
    # The task folder (run.json task.taskset_dir/task.name) says which files are official, when it is readable.
    rj = load_json(os.path.join(d, "run.json")) or {}; t = rj.get("task") or {}
    official = None; tdir = None
    if t.get("taskset_dir") and t.get("name"):
        tdir = os.path.join(t["taskset_dir"], t["name"], "tests")
        if os.path.isdir(tdir): official = {f for _, _, fs in os.walk(tdir) for f in fs}
        else: tdir = None
    own = {n: r for n, r in by.items() if official is None or os.path.basename(n.split("::")[0]) in official}
    extra = len(by) - len(own)
    failed = sorted(n.split("::")[-1] for n, r in own.items() if r in ("FAILED", "ERROR"))
    passed = sum(1 for r in own.values() if r in ("PASSED", "XPASS"))
    res = {"passed": passed, "failed": len(failed), "total": len(own), "failed_names": failed, "agent_written": extra,
           "summary": summ[-1] if summ else None}
    if full:
        det = failure_details(out); src = test_sources(tdir) if tdir else {}
        res["cases"] = [{"name": n.split("::")[-1], "file": os.path.basename(n.split("::")[0]), "result": r,
                         "own": n in own, "detail": det.get(n.split("::")[-1]),
                         "source": src.get(os.path.basename(n.split("::")[0]), {}).get(n.split("::")[-1])} for n, r in by.items()]
    return res


def summary(rid):
    """The run's run.json as written by run.sh (origin half before the run, result half merged in after), plus
    `run` (the folder name), `has_run_json`, and `calls` counted from calls.jsonl when the run has not finished."""
    d = os.path.join(RUNS, rid)
    rj = load_json(os.path.join(d, "run.json")) or {}
    out = {"run": rid, "has_run_json": bool(rj), **rj}
    if out.get("calls") is None:
        out["calls"] = sum(1 for l in read(os.path.join(d, "calls.jsonl"), "").splitlines() if l.strip())
    out["tests"] = tests(d)
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
    if verifier: verifier["tests"] = tests(d, full=True)
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

    def redirect(self, location, *cookies):
        self.send_response(302); self.send_header("Location", location)
        for c in cookies: self.send_header("Set-Cookie", c)
        self.send_header("Content-Length", "0"); self.send_header("Cache-Control", "no-store"); self.end_headers()

    def auth_route(self, parts, q):
        """The OAuth dance.  The browser only ever holds a signed session id; tokens stay in auth.SESSIONS."""
        if not auth.configured(): return self.json(404, {"error": "github sign-in is not configured"})
        if parts == ["github"]:
            state, cookie = auth.state_cookie()
            return self.redirect(auth.authorize_url(state), cookie)
        if parts == ["install"]:
            url = auth.install_url("")
            if not url: return self.send(404, "GITHUB_APP_SLUG is not set", "text/plain")
            state, cookie = auth.state_cookie()
            return self.redirect(auth.install_url(state), cookie)
        if parts == ["callback"]:
            code = (q.get("code") or [""])[0]
            if not code:
                # A bare install (the app does not ask for user authorization) comes back with
                # installation_id + setup_action and no state.  No token is minted here, so there
                # is nothing to CSRF-protect; just drop the user back into the picker.
                if (q.get("installation_id") or [""])[0]:
                    return self.redirect("/#import", auth.clear_state())
                return self.send(400, "no code in callback", "text/plain")
            if not auth.check_state(self.headers.get("Cookie"), (q.get("state") or [""])[0]):
                return self.send(400, "bad oauth state; start again at /auth/github", "text/plain")
            try: user = auth.exchange(code)
            except RuntimeError as e: return self.send(502, f"github sign-in failed: {e}", "text/plain")
            return self.redirect("/#import", auth.login(user), auth.clear_state())
        if parts == ["logout"]:
            return self.redirect("/", auth.logout(auth.session_id(self.headers.get("Cookie")) or ""))
        return self.json(404, {"error": "no such auth route"})

    def github_route(self, parts, q, sess):
        """Read-only GitHub reads on the user's behalf, so the frontend never handles a token."""
        try:
            if parts == ["installations"]: return self.json(200, auth.installations(sess))
            if parts == ["repos"]:
                inst = (q.get("installation") or [""])[0]
                if not inst.isdigit(): return self.json(400, {"error": "installation=<id> required"})
                return self.json(200, auth.repositories(sess, inst))
        except RuntimeError as e: return self.json(502, {"error": str(e)})
        return self.json(404, {"error": "no such api route"})

    def do_GET(self):
        path, _, query = self.path.partition("?")
        parts = [unquote(p) for p in path.strip("/").split("/") if p]
        q = parse_qs(query)
        if parts[:1] == ["auth"]: return self.auth_route(parts[1:], q)
        sess = auth.session_of(self.headers.get("Cookie")) if auth.configured() else None
        if parts[:1] == ["api"]:
            if parts[1:] == ["me"]: return self.json(200, {"auth": auth.configured(), "user": auth.public(sess),
                                                            "install_url": "/auth/install" if auth.install_url() else "", "can_clone": auth.can_clone()})
            if parts[1:] == ["runs"]: return self.json(200, [summary(r) for r in run_dirs()])
            if parts[1:2] == ["run"] and len(parts) == 3:
                d = find_run(parts[2])
                return self.json(200, bundle(d)) if d else self.json(404, {"error": "no such run"})
            if parts[1:2] == ["github"]:
                if not sess: return self.json(401, {"error": "sign in with github"})
                return self.github_route(parts[2:], q, sess)
            return self.json(404, {"error": "no such api route"})
        if parts[:1] == ["raw"] and len(parts) >= 3:
            d = find_run(parts[1]); p = os.path.realpath(os.path.join(d or "", *parts[2:]))
            if not d or not p.startswith(os.path.realpath(d) + os.sep) or not os.path.isfile(p): return self.send(404, "not found", "text/plain")
            ctype = "application/json" if p.endswith(".json") else "text/plain; charset=utf-8"
            return self.send(200, open(p, "rb").read(), ctype)
        # Anything the build wrote (hashed bundles, favicon, robots.txt) is served as-is.
        root = os.path.realpath(DIST)
        asset = os.path.realpath(os.path.join(root, *parts)) if parts else ""
        if asset.startswith(root + os.sep) and os.path.isfile(asset):
            return self.send(200, open(asset, "rb").read(), TYPES.get(os.path.splitext(asset)[1], "application/octet-stream"))
        # Everything else is one of the app's own routes; its router reads them off the URL.
        page = read(os.path.join(DIST, "index.html"))
        if page is None: return self.send(500, "web/dist is missing: npm --prefix web install && npm --prefix web run build", "text/plain")
        return self.send(200, page, "text/html; charset=utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=8789); ap.add_argument("--runs", default=RUNS)
    ap.add_argument("--dist", default=DIST, help="the built frontend (default web/dist)")
    a = ap.parse_args(); RUNS = os.path.abspath(a.runs); DIST = os.path.abspath(a.dist)
    if not os.path.isfile(os.path.join(DIST, "index.html")):
        print(f"warning: no index.html in {DIST} — run: npm --prefix web install && npm --prefix web run build", file=sys.stderr)
    mode = f"github sign-in as {auth.CLIENT_ID} ({auth.BASE_URL})" if auth.configured() else "open (no GITHUB_CLIENT_ID)"
    print(f"Harness Report on http://localhost:{a.port}   runs={RUNS}   auth={mode}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()
