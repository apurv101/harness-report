"""evals.py — start run.sh from the site and follow it.  One evaluation at a time on this machine.

An evaluation is one click on "Run task": run.sh on the chosen repository and the bowling task.  It lives in
evals/<id>/:

    eval.json      who started it, on what, the pid, and its status: running | done | failed | cancelled
    events.jsonl   what run.sh emits with HR_EVENTS set: stages, the recipe decision, the run folder, the result
    console.log    run.sh's terminal output, as-is

The run itself lands in runs/<id>-<task>/ like any other run, so the Runs page lists it the moment it starts, and
the proxy's calls.jsonl there is read as it grows for the live call count.  This is the same contract the AWS
control plane will serve (RUN-PLANE.md): POST to start, GET with an event cursor to follow.

Every status change is also published to the run store (lib/store.py) as EVAL#<id> — the evaluation, its stage
events and its console log, beside the runs it produced.  Best-effort: these three files are the record.
"""
import json, os, re, signal, subprocess, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
import ddb, store                                  # the DynamoDB copy: the evaluation, its events, its console log
EVALS = os.path.join(HERE, "evals")
RUNS = os.path.join(HERE, "runs")           # run.sh always writes here
TASKSET, TASK = "aider_polyglot", "polyglot_python_bowling"
REPO_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$")
EVAL_ID = re.compile(r"^\d{8}T\d{6}-[a-z0-9.-]{1,12}$")

LOCK = threading.Lock()
PROCS = {}      # eval id -> Popen, for evaluations this server process started
LIVE = {}       # eval id -> incremental read state of the run's calls.jsonl


class Busy(Exception):
    def __init__(self, ev): super().__init__("another evaluation is running"); self.eval = ev


def _path(eid, name=""): return os.path.join(EVALS, eid, name)


def _load(eid):
    try:
        with open(_path(eid, "eval.json")) as f: return json.load(f)
    except (OSError, ValueError): return None


def _save(ev):
    tmp = _path(ev["id"], "eval.json.tmp")
    with open(tmp, "w") as f: json.dump(ev, f, indent=2)
    os.replace(tmp, _path(ev["id"], "eval.json"))
    _publish(ev["id"])


def _publish(eid):
    """The evaluation into the run store, beside the runs it produced — its status, its stage events and the
    console log run.sh wrote.  Never fatal: eval.json on disk is the record, the table is the copy."""
    if not (os.environ.get("HR_DDB") or os.environ.get("HR_DDB_ENDPOINT") or os.environ.get("HR_TABLE")): return
    try: store.publish_eval(eid)
    except (ddb.Error, OSError, ValueError) as e: print(f"evals: not published: {e}", flush=True)


def _alive(ev):
    p = PROCS.get(ev["id"])
    if p is not None: return p.poll() is None
    try: os.kill(int(ev.get("pid") or 0), 0); return bool(ev.get("pid"))   # started by an earlier serve.py
    except (OSError, ValueError): return False


def _last_error(eid):
    msg = None
    for e in _read_events(eid):
        if e.get("type") == "error": msg = e.get("msg")
    return msg


def _settle(ev):
    """A running evaluation whose process has exited gets its final status, from run.json and run.sh's exit."""
    if ev.get("status") != "running" or _alive(ev): return ev
    p = PROCS.pop(ev["id"], None)
    if p is not None: ev["rc"] = p.returncode
    rj = None
    try:
        with open(os.path.join(RUNS, ev["run"], "run.json")) as f: rj = json.load(f)
    except (OSError, ValueError): pass
    finished = bool(rj and rj.get("finished"))
    ev["status"] = "cancelled" if ev.get("cancelled") else "done" if finished else "failed"
    ev["finished"] = ev.get("finished") or time.strftime("%Y-%m-%dT%H:%M:%S")
    if ev["status"] == "failed": ev["error"] = _last_error(ev["id"]) or f"run.sh exited with {ev.get('rc')}; see evals/{ev['id']}/console.log"
    _save(ev)
    return ev


def get(eid):
    if not EVAL_ID.match(eid or "") or not os.path.isdir(_path(eid)): return None
    with LOCK:
        ev = _load(eid)
        return _settle(ev) if ev else None


def current():
    """The evaluation still running on this machine, if any (also one started before serve.py restarted)."""
    with LOCK: return _current()


def _current():
    if not os.path.isdir(EVALS): return None
    for eid in sorted(os.listdir(EVALS), reverse=True):
        ev = _load(eid) if EVAL_ID.match(eid) else None
        if ev and ev.get("status") == "running":
            ev = _settle(ev)
            if ev["status"] == "running": return ev
    return None


def start(repo, user=None, token=None):
    """Start run.sh on github.com/<repo> × the bowling task.  Raises Busy while another evaluation runs."""
    with LOCK:
        cur = _current()
        if cur: raise Busy(cur)
        slug = re.sub(r"[^a-z0-9.-]", "-", repo.lower().replace("/", "-"))[:12]   # keeps hr-proxy-<run> under 63 chars
        eid = time.strftime("%Y%m%dT%H%M%S") + "-" + slug
        os.makedirs(_path(eid))
        ev = {"id": eid, "repo": repo, "url": f"https://github.com/{repo}", "taskset": TASKSET, "task": TASK,
              "run": f"{eid}-{TASK}", "user": user, "status": "running", "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "finished": None, "rc": None, "cancelled": False, "error": None, "pid": None}
        env = dict(os.environ, HR_EVENTS=_path(eid, "events.jsonl"))
        env.pop("HR_GIT_TOKEN", None)
        if token: env["HR_GIT_TOKEN"] = token
        with open(_path(eid, "console.log"), "wb") as log:
            p = subprocess.Popen(["bash", os.path.join(HERE, "run.sh"), ev["url"], "--taskset", TASKSET, "--tasks", TASK,
                                  "--run-id", eid], cwd=HERE, env=env, stdin=subprocess.DEVNULL, stdout=log,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        PROCS[eid] = p; ev["pid"] = p.pid
        _save(ev)

    def wait():
        p.wait()
        with LOCK:
            e = _load(eid)
            if e: _settle(e)
    threading.Thread(target=wait, daemon=True).start()
    return ev


def cancel(eid):
    with LOCK:
        ev = _load(eid) if EVAL_ID.match(eid or "") else None
        if not ev: return None
        if ev.get("status") == "running" and _alive(ev):
            ev["cancelled"] = True; _save(ev)
            try: os.killpg(int(ev["pid"]), signal.SIGTERM)   # run.sh's TERM trap removes its containers
            except (OSError, ValueError): pass
        return ev


def _read_events(eid):
    try:
        with open(_path(eid, "events.jsonl")) as f: data = f.read()
    except OSError: return []
    out = []
    for line in data.split("\n")[:-1]:          # only complete lines; the last one may still be being written
        try: out.append(json.loads(line))
        except ValueError: pass
    return out


def events(eid, after=0):
    evs = _read_events(eid)
    return evs[after:], len(evs)


def live(ev):
    """Model calls so far in the evaluation's run, read incrementally from the proxy's calls.jsonl."""
    st = LIVE.setdefault(ev["id"], {"offset": 0, "calls": 0, "input_tokens": 0, "output_tokens": 0, "errors": 0, "last_action": None})
    try:
        with open(os.path.join(RUNS, ev["run"], "calls.jsonl"), "rb") as f:
            f.seek(st["offset"]); chunk = f.read()
    except OSError: chunk = b""
    end = chunk.rfind(b"\n") + 1
    for line in chunk[:end].splitlines():
        try: c = json.loads(line)
        except ValueError: continue
        u = c.get("usage") or {}
        st["calls"] += 1; st["input_tokens"] += u.get("input_tokens") or 0; st["output_tokens"] += u.get("output_tokens") or 0
        if c.get("error"): st["errors"] += 1
        st["last_action"] = store.action(c) or st["last_action"]
    st["offset"] += end
    return {k: v for k, v in st.items() if k != "offset"}
