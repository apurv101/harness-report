"""evals.py — submit evaluations from the site and follow their progress.

An evaluation is one click on "Run task": run.sh on the chosen repository and one Harbor task.  The task is the
caller's pick from the runnable pool (lib/tasks.py: a candidate whose reference solution passes its own tests),
else the harness's top recommendation (lib/recommend.py), else bowling.  It lives in evals/<id>/:

    eval.json      who started it, on what, the pid, and its status: running | done | failed | cancelled
    events.jsonl   what run.sh emits with HR_EVENTS set: stages, the recipe decision, the run folder, the result
    console.log    run.sh's terminal output, as-is

The run itself lands in runs/<id>-<task>/ like any other run, so the Runs page lists it the moment it starts, and
the proxy's calls.jsonl there is read as it grows for the live call count.  This is the same contract the AWS
control plane will serve (RUN-PLANE.md): POST to start, GET with an event cursor to follow.

Every status change is also published to the run store (lib/store.py) as EVAL#<id> — the evaluation, its stage
events and its console log, beside the runs it produced.  Best-effort: these three files are the record.

HR_EVALS picks which half of that this process is:

    on      (default)  start run.sh here and follow the folder.  `python3 serve.py` on a laptop, and hr-agentd
    local-queue        durable SQLite jobs; a separate hr-local pool runs isolated attempts in parallel
    queue              enqueue the lease and read progress back out of the table.  The hosted API, which has
                       no Docker daemon and no disk — it never runs anything, it only records and reports
    off                refuse, with a reason

In queue mode the table is the record rather than a copy of one, because the process that creates an evaluation
and the process that runs it are not the same process and share no disk.  Every reader below is written to work
either way, so serve.py does not branch.
"""
import json, os, re, secrets, signal, subprocess, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
import ddb, leases, store                           # the DynamoDB copy: the evaluation, its events, its console log
DATA = os.path.abspath(os.environ.get("HR_DATA_DIR") or HERE)
EVALS = os.path.join(DATA, "evals")
RUNS = os.path.join(DATA, "runs")
DEFAULT = ("aider_polyglot", "polyglot_python_bowling")     # the first task when nothing better is known
DAILY_CAP = int(os.environ.get("HR_DAILY_CAP") or 5)        # evaluations one login may start per UTC day
REPO_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$")
EVAL_ID = re.compile(r"^\d{8}T\d{6}-[a-z0-9.-]{1,12}(?:-[a-f0-9]{12})?$")

# run.sh needs a Docker daemon and a writable tree.  A host with neither either hands the work to one that
# has both (queue) or says so (off), rather than raising.
MODE = (os.environ.get("HR_EVALS") or "on").strip().lower()
MODE = "off" if MODE in ("0", "off", "false", "no") else MODE
ENABLED = MODE != "off"
QUEUED = MODE == "queue"     # this process enqueues and reports; a runner elsewhere does the work
LOCAL_QUEUED = MODE == "local-queue"
LOCAL_USERS = LOCAL_QUEUED and os.environ.get("HR_LOCAL_USERS") == "1"
if LOCAL_QUEUED:
    from urllib.parse import urlsplit
    if urlsplit(ddb.endpoint() or "").hostname not in ("127.0.0.1", "localhost", "::1"):
        raise RuntimeError("local-queue requires HR_DDB=local and a loopback DynamoDB endpoint")


def local_queue():
    from localqueue import Queue
    return Queue(os.path.join(EVALS, "queue.sqlite3"))

LOCK = threading.Lock()
PROCS = {}      # eval id -> Popen, for evaluations this server process started
LIVE = {}       # eval id -> incremental read state of the run's calls.jsonl


class Busy(Exception):
    def __init__(self, ev): super().__init__("another evaluation is running"); self.eval = ev


class Refused(Exception):
    """A request this server will not start: a task the site does not offer, or a login over its daily cap."""


harness_name = store.harness_name


def _runnable():
    """{(taskset, task)} the site may start — the RUNNABLE rows when a table answers, else the catalog on disk."""
    try:
        if store.available(): return {(t["taskset"], t["task"]) for t in store.runnable_list()}
    except ddb.Error: pass
    try:
        import tasks
        return tasks.runnable_set()
    except (OSError, ValueError, ImportError): return set()


def pick_task(repo, taskset=None, task=None):
    """The (taskset, task) an evaluation runs.  An explicit pick must be in the runnable pool; with no pick, the
    harness's first recommendation that is still runnable, else the default."""
    pool = _runnable()
    if taskset or task:
        if (taskset, task) not in pool and (taskset, task) != DEFAULT:
            raise Refused(f"{taskset}/{task} is not a task the site can run yet")
        return taskset, task
    try:
        recs = store.harness_recs(harness_name(repo)) if store.available() else None
    except ddb.Error: recs = None
    for r in (recs or {}).get("recs") or []:
        if (r.get("taskset"), r.get("task")) in pool: return r["taskset"], r["task"]
    return DEFAULT


def check_cap(user):
    """At most DAILY_CAP evaluations per login per UTC day.  Unsigned local use (user None) is not capped."""
    if not user or DAILY_CAP <= 0: return
    today = time.strftime("%Y%m%d", time.gmtime())
    try: rows = store.evals_list(limit=200) if (QUEUED or store.available()) else []
    except ddb.Error: rows = []
    if not rows and os.path.isdir(EVALS):
        rows = [e for e in (_load(x) for x in os.listdir(EVALS) if EVAL_ID.match(x)) if e]
    n = sum(1 for e in rows if e.get("user") == user and (e.get("id") or "").startswith(today)
            and e.get("status") != "cancelled")
    if n >= DAILY_CAP:
        raise Refused(f"{user} has started {n} evaluations today; the limit is {DAILY_CAP} a day")


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
    if ev["status"] == "done": after_run(ev)
    return ev


def after_run(ev):
    """A finished run changes what the harness should run next: profile it (once per commit) and re-rank, in a
    detached process so neither a request thread nor the runner waits the minute that takes."""
    if os.environ.get("HR_RECOMMEND") == "off": return
    if not (os.environ.get("HR_DDB") or os.environ.get("HR_DDB_ENDPOINT") or os.environ.get("HR_TABLE")): return
    import recommend
    name = ev.get("harness") or harness_name(ev["repo"])
    src = os.path.join(DATA, "work", "jobs", ev["id"], name, "repo") if LOCAL_QUEUED or os.environ.get("HR_ISOLATED_RUN") == "1" else None
    recommend.spawn_refresh(name, src=src)


def get(eid):
    if not EVAL_ID.match(eid or ""): return None
    if LOCAL_QUEUED: return local_queue().get(eid)
    if QUEUED:
        import cloudqueue
        state = cloudqueue.get(eid)
        report = store.eval_record(eid)
        return {**(report or {}), **state} if state else report
    if not os.path.isdir(_path(eid)): return None
    with LOCK:
        ev = _load(eid)
        return _settle(ev) if ev else None


def current(user=None, repo=None):
    """An active evaluation for this owner in queue modes; the singleton in legacy local mode."""
    if LOCAL_QUEUED:
        return next((e for e in local_queue().active(user or "local")
                     if not repo or e["repo"].lower() == repo.lower()), None)
    if QUEUED:
        import cloudqueue
        return next((e for e in cloudqueue.recent(user or "local") if e["status"] in ("queued", "running")
                     and (not repo or e["repo"].lower() == repo.lower())), None)
    with LOCK: return _current()


def _current():
    if not os.path.isdir(EVALS): return None
    for eid in sorted(os.listdir(EVALS), reverse=True):
        ev = _load(eid) if EVAL_ID.match(eid) else None
        if ev and ev.get("status") == "running":
            ev = _settle(ev)
            if ev["status"] == "running": return ev
    return None


def _record(repo, eid, user, status, taskset=DEFAULT[0], task=DEFAULT[1]):
    return {"id": eid, "repo": repo, "url": f"https://github.com/{repo}", "taskset": taskset, "task": task,
            "harness": harness_name(repo), "run": f"{eid}-{task}", "user": user, "status": status,
            "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "finished": None, "rc": None,
            "cancelled": False, "error": None, "pid": None}


def _eid(repo):
    slug = re.sub(r"[^a-z0-9.-]", "-", repo.lower().replace("/", "-"))[:12]
    return time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + "-" + slug + "-" + secrets.token_hex(6)


def enqueue(repo, user=None, installation=None, taskset=None, task=None):
    """Put one evaluation on the lease queue and record it as queued.  What the hosted API does instead of
    starting anything: it owns the record, a runner owns the work.

    The lease carries the installation id, never a clone token — a token in a queue is a secret sitting in a
    queue, and the runner can mint its own from the app key it already needs for everything else."""
    import cloudqueue
    if not user: raise Refused("sign in with GitHub to queue an evaluation")
    taskset, task = pick_task(repo, taskset, task)
    eid = _eid(repo)
    ev = _record(repo, eid, user, "queued", taskset, task)
    ev["installation"] = installation
    try: ev = cloudqueue.enqueue(ev, DAILY_CAP)
    except cloudqueue.Limit as e: raise Refused(str(e)) from e
    try:
        leases.send({"eval": eid, "repo": repo, "url": ev["url"], "taskset": taskset, "task": task,
                    "run": ev["run"], "user": user, "installation": installation})
    except leases.Error as e:
        cloudqueue.update(eid, {"status": "failed", "finished": cloudqueue.stamp(), "error": f"could not queue it: {e}"},
                          expected=lambda e: e["status"] == "queued")
        raise
    cloudqueue.wake()
    return ev


def start(repo, user=None, token=None, installation=None, taskset=None, task=None):
    """Start run.sh on github.com/<repo> × one runnable task.  Raises Busy while another evaluation runs, and
    Refused for a task the site does not offer or a login over its daily cap.

    In queue mode nothing starts here; the lease goes on the queue and a runner picks it up."""
    if LOCAL_QUEUED:
        from localqueue import Limit
        taskset, task = pick_task(repo, taskset, task)
        eid = _eid(repo)
        ev = _record(repo, eid, user or "local", "queued", taskset, task)
        ev["installation"] = installation
        os.makedirs(_path(eid), exist_ok=True)
        try: ev = local_queue().enqueue(ev, DAILY_CAP if user else 0)
        except Limit as e: raise Refused(str(e)) from e
        return ev
    if QUEUED: return enqueue(repo, user=user, installation=installation, taskset=taskset, task=task)
    with LOCK:
        cur = _current()
        if cur: raise Busy(cur)
        check_cap(user)
        taskset, task = pick_task(repo, taskset, task)
        eid = _eid(repo)
        os.makedirs(_path(eid))
        ev = _record(repo, eid, user, "running", taskset, task)
        env = dict(os.environ, HR_EVENTS=_path(eid, "events.jsonl"))
        env.pop("HR_GIT_TOKEN", None)
        if token: env["HR_GIT_TOKEN"] = token
        with open(_path(eid, "console.log"), "wb") as log:
            p = subprocess.Popen(["bash", os.path.join(HERE, "run.sh"), ev["url"], "--taskset", taskset, "--tasks", task,
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


def cancel_queued(eid):
    """Stop an evaluation this process is not running.

    Two cases, and conflating them wedges the site.  A *running* one has a process on some runner, so all that
    can be done here is write the intent: hr-agentd re-reads the record while it works and does the killing.
    A *queued* one has no process to signal, so it is settled to cancelled outright — leaving it queued would
    leave `running_eval()` returning it forever, and one-at-a-time would refuse every later run with a 409
    naming a lease nobody is working on.  Its message stays on the queue and the runner drops it on sight."""
    import cloudqueue
    if cloudqueue.get(eid): return cloudqueue.cancel(eid)
    ev = store.eval_record(eid)
    if not ev: return None
    if ev.get("status") == "queued":
        ev.update(cancelled=True, status="cancelled", finished=time.strftime("%Y-%m-%dT%H:%M:%S"),
                  error="cancelled before it was leased")
        store.publish_card(ev)
    elif ev.get("status") == "running":
        ev["cancelled"] = True
        store.publish_card(ev)
    return ev


def cancel(eid):
    if LOCAL_QUEUED: return local_queue().cancel(eid)
    if QUEUED: return cancel_queued(eid)
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


def console(eid, after=0):
    """run.sh's own terminal output for this evaluation, from byte `after` on.  This is the only place the fetch,
    the analyzer's turns and the docker build appear — the events are stage banners, not output — so the site reads
    it the same way it reads the call count: an offset, and whatever has been written since."""
    if QUEUED:
        # The runner publishes the log onto the record, trimmed to fit a row, so the offset is into that copy.
        text = (store.eval_record(eid) or {}).get("console") or ""
        raw = text.encode()
        after = max(0, min(int(after or 0), len(raw)))
        return {"text": raw[after:].decode("utf-8", "replace"), "next": len(raw), "bytes": len(raw)}
    path = _path(eid, "console.log")
    try: size = os.path.getsize(path)
    except OSError: return {"text": "", "next": 0, "bytes": 0}
    after = max(0, min(int(after or 0), size))
    with open(path, "rb") as f:
        f.seek(after); chunk = f.read()
    # A read can land mid-character while run.sh is writing; the replacement char is better than a failed poll.
    return {"text": chunk.decode("utf-8", "replace"), "next": after + len(chunk), "bytes": size}


def events(eid, after=0):
    if QUEUED: return store.eval_events(eid, after)
    evs = _read_events(eid)
    return evs[after:], len(evs)


def live(ev):
    """Model calls so far in the evaluation's run, read incrementally from the proxy's calls.jsonl.

    In queue mode the file is on the runner's disk, not this one, so the runner computes exactly this dict and
    republishes it on the record as it goes; here it is only read back."""
    if QUEUED: return (ev or {}).get("live") or {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                                                 "errors": 0, "last_action": None}
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
