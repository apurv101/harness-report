#!/usr/bin/env python3
"""serve.py — the Harness Report site and read-only run API.  No dependencies beyond python3.

    npm --prefix web install && npm --prefix web run build     # the frontend, once
    python3 serve.py                 # serves web/dist and runs/ on http://localhost:8789
    python3 serve.py --port 9000 --runs /path/to/runs --dist /path/to/dist

URLs
    /                              product landing
    /runs                          recorded evaluations
    /runs/<run-id>                 run detail
    /<run-id>                      legacy run link (opens the same frontend)
    /api/runs                      JSON list of runs (summary of each run.json)
    /api/run/<run-id>              JSON bundle: run.json, task, command, recipe, calls[], logs, files[]
    /api/run/<run-id>/files        just the file list, cheap enough to poll while the run is still writing
                                   both come from the DynamoDB table when one answers (lib/store.py, --store),
                                   and from the run folders when it does not — the same JSON either way
    /raw/<run-id>/<file>           a file from the run folder as-is
    /auth/github                   start "Sign in with GitHub"; /auth/callback finishes it, /auth/logout ends it
    /api/me                        whether auth is on, and who is signed in
    /api/github/installations      the app installations the signed-in user has
    /api/github/repos?installation=<id>   the repositories one installation grants
    POST /api/evals {"repo": "owner/name", "taskset"?, "task"?}  start run.sh on that repo × one runnable task —
                                   the one named, else the harness's first recommendation, else bowling
                                   (one at a time: 409 if busy; 400 for a task the site does not offer; 429 over the daily cap)
    /api/evals/current             the evaluation running now, or null
    /api/evals/<id>?after=<n>      follow one: its status, events from n on, live model calls, and the result when done
    /api/evals/<id>/console?after=<bytes>   run.sh's own terminal output from that byte on (&format=text for the whole log)
    POST /api/evals/<id>/cancel    stop it (run.sh removes its containers on the way out)

Pages for people and agents (lib/pages.py) — each is the app's HTML with its own title, description and a
<noscript> Markdown copy; add .md or .json to any of them for the Markdown or the object:
    /harnesses  /harnesses/<name>  /tasks  /tasks/<taskset>  /tasks/<taskset>/<task>  /runs/<run-id>
    /api/harnesses[/<name>]  /api/tasksets[/<taskset>?after=]  /api/tasks/<taskset>/<task>  /api/runnable
    /api/harnesses/<name>/recs     the tests recommended next (lib/recommend.py), or null before the first run
    /api/first-task?repo=o/n&language=&description=   the task a repo should start with
    /llms.txt  /llms-full.txt  /sitemap.xml  /sitemaps/<name>.xml
    POST /mcp                      MCP over streamable HTTP, read-only (lib/mcp.py)

The frontend is the React app in web/; `npm --prefix web run build` writes web/dist, and everything under
it is served as-is with index.html as the fallback for the app's own routes.  `npm --prefix web run dev`
serves it on :5173 instead and proxies /api, /auth and /raw back here.

Sign-in is optional: with no GITHUB_CLIENT_ID in the environment nobody can sign in at all.  Either way the
runs are public; only /api/github/* needs the session cookie.  See auth.py for the env it reads.

Every run is one folder runs/<run-id>/; its run.json says what harness (harness.name/repo/commit), what task
(kind prompt|harbor, task.name/taskset, prompt) and what model it ran, plus rc/seconds/reward/calls once finished.
"""
import argparse, json, os, sys
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import quote, unquote, parse_qs, urlsplit

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import auth, ddb, evals, leases, mcp, pages, recommend, store, verifier

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.abspath(os.path.join(HERE, "web", "dist"))     # the built frontend
RUNS = evals.RUNS

TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".json": "application/json", ".svg": "image/svg+xml",
         ".txt": "text/plain; charset=utf-8", ".xml": "application/xml", ".ico": "image/x-icon",
         ".png": "image/png", ".webp": "image/webp", ".woff2": "font/woff2", ".map": "application/json"}

TEXT_FILES = ("task.txt", "command.sh", "stdout.log", "stderr.log", "proxy.log")   # inlined into the bundle
CORE = TEXT_FILES + ("run.json", "recipe.json", "calls.jsonl")                     # everything else is "other"


STORE = "auto"      # --store: auto (the table when it answers) | table | files


def from_table(fn, *a):
    """The table's answer, or None to fall through to the folders.  A stopped container or an expired credential
    must degrade to reading runs/ rather than take the site down — and it says so once, on stderr."""
    if STORE == "files" or (STORE == "auto" and not store.available()): return None
    try: return fn(*a)
    except ddb.Error as e:
        sys.stderr.write(f"store: {e}\n")
        return None


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
    out["tests"] = verifier.parse(d)
    return out


def files_of(d):
    """Every file in a run folder, by name: what the Files tab lists, and what a run in flight is polled for."""
    files = []
    for root, _, fs in os.walk(d):
        for f in fs:
            p = os.path.join(root, f); rel = os.path.relpath(p, d)
            try: size = os.path.getsize(p)
            except OSError: continue       # a harness can leave a dangling symlink behind (claude-config/debug/latest)
            files.append({"name": rel, "bytes": size, "core": rel in CORE})
    files.sort(key=lambda x: x["name"])
    return files


def jsonl(path):
    """Every record in a .jsonl, and the count of lines too broken to parse — a half-written last line is
    normal while the run is still going, so a bad line is counted, never fatal."""
    out, bad = [], 0
    for line in (read(path, "")).splitlines():
        if not line.strip(): continue
        try: out.append(json.loads(line))
        except ValueError: bad += 1
    return out, bad


def bundle(d):
    rid = os.path.basename(d)
    calls, bad = jsonl(os.path.join(d, "calls.jsonl"))
    egress, _ = jsonl(os.path.join(d, "egress.jsonl"))
    files = files_of(d)
    verified = {k: read(os.path.join(d, "verifier", k)) for k in ("stdout.log", "stderr.log", "reward.txt")} if os.path.isdir(os.path.join(d, "verifier")) else None
    if verified: verified["tests"] = verifier.parse(d, full=True)
    return {"run": rid, "run_json": summary(rid),
            "recipe": load_json(os.path.join(d, "recipe.json")),
            "calls": calls, "calls_unparsed": bad, "egress": egress,
            **{k.split(".")[0]: read(os.path.join(d, k)) for k in TEXT_FILES},
            "verifier": verified, "files": files, "files_omitted": 0, "source": "files", "truncated": []}


# A function url answers with at most 6 MB, base64-encoded, so about 4.7 MB of JSON.  Every request of an agent loop
# carries the whole conversation so far, so a long run's calls outgrow that long before anything else does.
BUNDLE_MAX = int(os.environ.get("HR_BUNDLE_MAX_BYTES") or (4_000_000 if os.environ.get("AWS_LAMBDA_FUNCTION_NAME") else 0))
KEEP_FIELD = 2_000


def fit_bundle(b, limit=None):
    """A bundle that fits `limit` bytes of JSON.  Over it, every call but the last loses the request fields bigger
    than KEEP_FIELD (the messages, the tools), then the same of its response; `request_trimmed` / `response_trimmed`
    keep what was there, and `calls_trimmed` counts the calls cut.  The last call stays whole: its request plus its
    response is the full conversation, which is what the trajectory is drawn from.  calls.jsonl has everything."""
    limit = BUNDLE_MAX if limit is None else limit
    if not limit or len(json.dumps(b)) <= limit: return b
    calls = [dict(c) for c in b.get("calls") or []]
    for field in ("request", "response"):
        for c in calls[:-1]:
            v = c.get(field)
            if not isinstance(v, dict): continue
            big = {k for k, x in v.items() if len(json.dumps(x)) > KEEP_FIELD}
            if not big: continue
            c[field] = {k: x for k, x in v.items() if k not in big}
            c[f"{field}_trimmed"] = {"fields": sorted(big), "bytes": len(json.dumps(v)),
                                    "messages": len(v.get("messages") or v.get("input") or []) if isinstance(v.get("messages") or v.get("input"), list) else None}
        out = {**b, "calls": calls, "calls_trimmed": sum(1 for c in calls if c.get("request_trimmed") or c.get("response_trimmed"))}
        if len(json.dumps(out)) <= limit: return out
    return out


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
        if evals.LOCAL_USERS:
            if parts == ["local"]:
                user = (q.get("user") or [""])[0]
                if user not in ("alice", "bob", "charlie"):
                    return self.json(400, {"error": "choose alice, bob or charlie"})
                return self.redirect("/import", f"hr_local_user={user}; Path=/; HttpOnly; SameSite=Lax")
            if parts == ["logout"]:
                return self.redirect("/", "hr_local_user=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")
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
                    return self.redirect("/import", auth.clear_state())
                return self.send(400, "no code in callback", "text/plain")
            if not auth.check_state(self.headers.get("Cookie"), (q.get("state") or [""])[0]):
                return self.send(400, "bad oauth state; start again at /auth/github", "text/plain")
            try: user = auth.exchange(code)
            except RuntimeError as e: return self.send(502, f"github sign-in failed: {e}", "text/plain")
            return self.redirect("/import", auth.login(user), auth.clear_state())
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

    def session(self):
        if evals.LOCAL_USERS:
            cookie = SimpleCookie()
            try: cookie.load(self.headers.get("Cookie") or "")
            except Exception: return None
            user = cookie.get("hr_local_user")
            return {"login": user.value, "local": True} if user and user.value in ("alice", "bob", "charlie") else None
        return auth.session_of(self.headers.get("Cookie")) if auth.configured() else None

    def owns_eval(self, ev):
        if not (evals.LOCAL_QUEUED or evals.QUEUED): return True
        sess = self.session()
        user = (sess or {}).get("login") or "local"
        return ev.get("user") == user

    def eval_state(self, ev, after):
        """What the site polls: the evaluation, run.sh's events from `after` on, the live calls, and the run's
        summary (reward, tests, calls) once it has finished.

        The result comes from the run folder when this machine has one and from the table when it does not, the
        same way /api/runs does — a run produced on a runner is a row here, never a folder."""
        evs, nxt = evals.events(ev["id"], after)
        finished = ev["status"] not in ("queued", "running")
        result = None
        if finished:
            result = summary(ev["run"]) if find_run(ev["run"]) else from_table(store.run_card, ev["run"])
        return {"eval": {k: v for k, v in ev.items() if k not in ("pid", "installation", "claim", "revision", "cap_counted", "lease_until")}, "events": evs, "next": nxt,
                "live": evals.live(ev), "result": result}

    def eval_console(self, eid, q):
        """The evaluation's console log: JSON with a byte cursor for the live view, or text/plain to open it whole."""
        ev = evals.get(eid)
        if not ev: return self.json(404, {"error": "no such evaluation"})
        if not self.owns_eval(ev): return self.json(403, {"error": "this evaluation belongs to another user"})
        out = evals.console(eid, int((q.get("after") or ["0"])[0] or 0))
        if (q.get("format") or [""])[0] == "text":
            return self.send(200, evals.console(eid, 0)["text"], "text/plain; charset=utf-8")
        return self.json(200, {**out, "status": ev["status"]})

    def evals_get(self, parts, q):
        if (evals.LOCAL_QUEUED or evals.QUEUED) and parts == []:
            user = (self.session() or {}).get("login") or "local"
            if evals.QUEUED:
                import cloudqueue
                rows = cloudqueue.recent(user)
            else: rows = evals.local_queue().recent(user)
            return self.json(200, {"evals": [{k: v for k, v in e.items() if k not in ("pid", "installation", "claim", "revision", "cap_counted", "lease_until")}
                                          for e in rows]})
        if parts == ["current"]:
            ev = evals.current((self.session() or {}).get("login"), (q.get("repo") or [None])[0])
            return self.json(200, self.eval_state(ev, 0) if ev else None)
        if len(parts) == 2 and parts[1] == "console": return self.eval_console(parts[0], q)
        if len(parts) == 1:
            ev = evals.get(parts[0])
            if not ev: return self.json(404, {"error": "no such evaluation"})
            if not self.owns_eval(ev): return self.json(403, {"error": "this evaluation belongs to another user"})
            try: after = max(0, int((q.get("after") or ["0"])[0]))
            except ValueError: after = 0
            return self.json(200, self.eval_state(ev, after))
        return self.json(404, {"error": "no such api route"})

    def installation_of(self, sess, repo):
        """Which of the signed-in user's installations grants this repository, and whether it is private.
        (None, False) when nothing does — a public repo is cloned anonymously and needs neither."""
        if not sess or sess.get("local") or not auth.can_clone(): return None, False
        for inst in auth.installations(sess):
            for r in auth.repositories(sess, inst["id"]):
                if r["name"].lower() == repo.lower():
                    return inst["id"], bool(r["private"])
        return None, False

    def clone_token(self, sess, repo):
        """A short-lived clone token when the signed-in user's GitHub App installations grant this repo and it is
        private.  None for a public repo (cloned anonymously).  PermissionError for a private repo we cannot reach."""
        inst, private = self.installation_of(sess, repo)
        return auth.clone_token(inst)[0] if (inst and private) else None

    def mcp_post(self):
        """MCP over streamable HTTP.  Open to any origin on purpose — it is read-only, and agents are not browsers."""
        n = int(self.headers.get("Content-Length") or 0)
        if n > 1_000_000: return self.json(413, {"error": "too large"})
        code, out = mcp.handle_body(self.rfile.read(n))
        if out is None:
            self.send_response(202); self.send_header("Content-Length", "0"); self.end_headers(); return
        return self.json(code, out)

    def do_POST(self):
        path = self.path.partition("?")[0]
        parts = [unquote(p) for p in path.strip("/").split("/") if p]
        if parts == ["mcp"]: return self.mcp_post()
        if parts[:2] != ["api", "evals"]: return self.json(404, {"error": "no such api route"})
        if not evals.ENABLED: return self.json(503, {"error": "this server does not start runs"})
        # The site's own pages only: a cross-site form or fetch carries another Origin (and cannot send JSON without CORS)
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc != self.headers.get("Host"): return self.json(403, {"error": "cross-origin request"})
        if not (self.headers.get("Content-Type") or "").startswith("application/json"): return self.json(415, {"error": "send JSON"})
        sess = self.session()
        if (auth.configured() or evals.LOCAL_USERS or evals.QUEUED) and not sess: return self.json(401, {"error": "sign in to start an evaluation"})
        try: body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError: return self.json(400, {"error": "bad json"})
        if parts[2:] == []:
            repo = str(body.get("repo") or "").strip().removesuffix(".git")
            if not evals.REPO_NAME.match(repo): return self.json(400, {"error": "repo must look like owner/name"})
            # A queued run is handed to a runner, which mints its own token from the app key; only a run started
            # here needs one now.  Either way the token never travels through the queue.
            try:
                inst, private = self.installation_of(sess, repo)
                token = None if (evals.QUEUED or evals.LOCAL_QUEUED) else (auth.clone_token(inst)[0] if (inst and private) else None)
            except RuntimeError as e: return self.json(502, {"error": f"could not reach GitHub: {e}"})
            taskset, task = (str(body.get(k) or "").strip() or None for k in ("taskset", "task"))
            try: ev = evals.start(repo, user=(sess or {}).get("login"), token=token,
                                  installation=inst if private else None, taskset=taskset, task=task)
            except evals.Refused as r:
                return self.json(429 if "limit" in str(r) else 400, {"error": str(r)})
            except evals.Busy as b: return self.json(409, {"error": f"{b.eval['repo']} is already running; one evaluation at a time", "eval": b.eval["id"]})
            except leases.Error as e: return self.json(503, {"error": f"the run queue is not reachable: {e}"})
            except ddb.Error as e: return self.json(503, {"error": f"the job store is not reachable: {e}"})
            return self.json(201, self.eval_state(ev, 0))
        if len(parts) == 4 and parts[3] == "cancel":
            ev = evals.get(parts[2])
            if ev and not self.owns_eval(ev): return self.json(403, {"error": "this evaluation belongs to another user"})
            ev = evals.cancel(parts[2])
            return self.json(200, {"eval": ev["id"], "cancelled": bool(ev.get("cancelled"))}) if ev else self.json(404, {"error": "no such evaluation"})
        return self.json(404, {"error": "no such api route"})

    def entity(self, fn):
        obj = from_table(fn)
        return self.json(200, obj) if obj is not None else self.json(503, {"error": "the run store is not answering"})

    def page_route(self, parts, q, fmt):
        """One of the public pages, as the app's HTML (with this page's head and a Markdown copy), as Markdown, or
        as the object both are rendered from.  A page the table does not know is the app's own 404 in HTML."""
        found = from_table(pages.resolve, parts, q)
        if fmt == "json":
            return self.json(200, found[0]) if found else self.json(404, {"error": "not found"})
        if fmt == "md":
            return self.send(200, found[1], "text/markdown; charset=utf-8") if found else self.send(404, "not found\n", "text/markdown")
        page = read(os.path.join(DIST, "index.html"))
        if page is None: return self.send(500, "web/dist is missing: npm --prefix web run build", "text/plain")
        if found:
            path = "/" + "/".join(quote(p, safe="") for p in parts)
            page = pages.noscript(pages.head(page, path, found[2], found[3], path), found[1])
        missing = not found and parts != ["runs"] and STORE != "files" and store.available()
        return self.send(404 if missing else 200, page, "text/html; charset=utf-8")

    def do_GET(self):
        path, _, query = self.path.partition("?")
        parts = [unquote(p) for p in path.strip("/").split("/") if p]
        q = parse_qs(query)
        if parts[:1] == ["auth"]: return self.auth_route(parts[1:], q)
        sess = self.session()
        if parts[:1] == ["api"]:
            if parts[1:] == ["me"]: return self.json(200, {"auth": auth.configured() or evals.LOCAL_USERS,
                                                            "local_users": evals.LOCAL_USERS, "eval_mode": evals.MODE,
                                                            "user": {"login": sess["login"], "id": 0, "avatar": "", "name": sess["login"]} if sess and sess.get("local") else auth.public(sess),
                                                            "install_url": "/auth/install" if not evals.LOCAL_USERS and auth.install_url() else "",
                                                            "can_clone": not evals.LOCAL_USERS and auth.can_clone()})
            if parts[1:] == ["runs"]:
                return self.json(200, from_table(store.runs_list) or [summary(r) for r in run_dirs()])
            if parts[1:2] == ["run"] and len(parts) == 4 and parts[3] == "files":
                # what the run has written so far: the folder while it is being written, the stored manifest after
                d = find_run(parts[2])
                if d: return self.json(200, {"run": parts[2], "files": files_of(d), "files_omitted": 0, "source": "files"})
                listed = from_table(store.run_files, parts[2])
                return self.json(200, listed) if listed else self.json(404, {"error": "no such run"})
            if parts[1:2] == ["run"] and len(parts) == 3:
                b = from_table(store.run_bundle, parts[2])
                # A run still being written is read from the folder it is being written into: the table has its card
                # from the moment it starts, but the calls, the logs and the files are only published at the end.
                if b and (b["run_json"].get("finished") or not find_run(parts[2])): return self.json(200, fit_bundle(b))
                d = find_run(parts[2])
                return self.json(200, fit_bundle(bundle(d))) if d else self.json(404, {"error": "no such run"})
            if parts[1:2] == ["github"]:
                if not sess: return self.json(401, {"error": "sign in with github"})
                if sess.get("local"): return self.json(200, [])
                return self.github_route(parts[2:], q, sess)
            if parts[1:2] == ["evals"]: return self.evals_get(parts[2:], q)
            if parts[1:] == ["runnable"]: return self.entity(lambda: pages.runnable())
            if parts[1:] == ["first-task"]:
                one = lambda k: ((q.get(k) or [""])[0] or None)
                repo = one("repo") or ""
                if not evals.REPO_NAME.match(repo): return self.json(400, {"error": "repo=owner/name required"})
                return self.json(200, from_table(recommend.first, repo, one("language"), one("description")))
            if len(parts) == 4 and parts[1] == "harnesses" and parts[3] == "recs":
                return self.json(200, from_table(store.harness_recs, parts[2]))
            if parts[1:2] in (["harnesses"], ["tasksets"], ["tasks"]):
                page = {"tasksets": "tasks"}.get(parts[1], parts[1])
                if parts[1] == "tasks" and len(parts) != 4: return self.json(404, {"error": "use /api/tasks/<taskset>/<task>"})
                return self.page_route([page, *parts[2:]], q, "json")
            return self.json(404, {"error": "no such api route"})
        if parts == ["mcp"]: return self.json(405, {"error": "POST JSON-RPC messages here (MCP streamable HTTP)"})
        if parts in (["llms.txt"], ["llms-full.txt"]):
            text = from_table(pages.llms, parts == ["llms-full.txt"])
            return self.send(200, text, "text/plain; charset=utf-8") if text else self.send(503, "the run store is not answering", "text/plain")
        if parts == ["sitemap.xml"] or (len(parts) == 2 and parts[0] == "sitemaps" and parts[1].endswith(".xml")):
            xml = from_table(pages.sitemap, None if parts == ["sitemap.xml"] else parts[1][:-4])
            return self.send(200, xml, "application/xml") if xml else self.send(404, "no such sitemap", "text/plain")
        last = parts[-1] if parts else ""
        fmt = "md" if last.endswith(".md") else "json" if last.endswith(".json") else "html"
        bare = [*parts[:-1], last.rsplit(".", 1)[0]] if fmt != "html" else parts
        if bare and bare[0] in pages.PAGE_ROOTS and (len(bare) >= 2 or bare[0] != "runs" or fmt != "html"):
            parts = bare
            return self.page_route(parts, q, fmt)
        if parts[:1] == ["raw"] and len(parts) >= 3:
            if any(p in (".", "..") or "/" in p or "\\" in p for p in parts[1:]):
                return self.send(400, "invalid file path", "text/plain")
            d = find_run(parts[1]); p = os.path.realpath(os.path.join(d or "", *parts[2:]))
            if not d or not p.startswith(os.path.realpath(d) + os.sep) or not os.path.isfile(p):
                try: archived = store.archived_file_url(parts[1], "/".join(parts[2:]))
                except Exception:
                    return self.send(503, "The complete log could not be loaded. Please try again.", "text/plain")
                if archived: return self.redirect(archived)
                # no folder on this machine (a run synced from elsewhere): the stored text of the file, if it is stored
                text = from_table(store.file_text, parts[1], "/".join(parts[2:]))
                if text is None: return self.send(404, "not found", "text/plain")
                return self.send(200, text, "text/plain; charset=utf-8")
            ctype = "application/json" if p.endswith(".json") else "text/plain; charset=utf-8"
            with open(p, "rb") as source: contents = source.read()
            return self.send(200, contents, ctype)
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
    ap.add_argument("--store", choices=("auto", "table", "files"), default="auto",
                    help="where the runs come from: auto (the DynamoDB table when it answers, else the folders)")
    a = ap.parse_args(); RUNS = os.path.abspath(a.runs); DIST = os.path.abspath(a.dist); STORE = a.store
    if not os.path.isfile(os.path.join(DIST, "index.html")):
        print(f"warning: no index.html in {DIST} — run: npm --prefix web install && npm --prefix web run build", file=sys.stderr)
    mode = "local test users (alice, bob, charlie)" if evals.LOCAL_USERS else f"github sign-in as {auth.CLIENT_ID} ({auth.BASE_URL})" if auth.configured() else "open (no GITHUB_CLIENT_ID)"
    src = "the run folders" if STORE == "files" else f"{ddb.target()}" + ("" if store.available() else " — NOT answering, reading the run folders")
    print(f"Harness Report on http://localhost:{a.port}   runs={RUNS}   auth={mode}\n  runs from: {src}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()
