"""A bounded local worker pool. Every job runs the ordinary runner in its own process group."""
import concurrent.futures
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time

from localqueue import Queue


def stop_process(pid, eid, sig=signal.SIGTERM):
    """Only signal our recorded run.sh process group, never an unrelated reused PID."""
    if not pid: return
    found = subprocess.run(["ps", "-p", str(pid), "-o", "args="], capture_output=True, text=True)
    if eid not in found.stdout or "run.sh" not in found.stdout: return
    try:
        if os.getpgid(pid) != pid: return
        os.killpg(pid, sig)
        return True
    except ProcessLookupError: return


def cleanup(eid):
    """Labels restrict cleanup to this job's containers, networks and task volumes."""
    for kind in ("container", "network", "volume"):
        result = subprocess.run(["docker", kind, "ls", "-q", "--filter", f"label=hr.evaluation={eid}",
                                 *(["-a"] if kind == "container" else [])], capture_output=True, text=True, timeout=30)
        if result.returncode: raise RuntimeError(f"could not inspect Docker {kind}s for {eid}: {result.stderr.strip()}")
        ids = result.stdout.split()
        if ids:
            result = subprocess.run(["docker", kind, "rm", *(["-f", "-v"] if kind == "container" else []), *ids],
                                    capture_output=True, text=True, timeout=30)
            if result.returncode: raise RuntimeError(f"could not clean Docker {kind}s for {eid}: {result.stderr.strip()}")


class Runner:
    def __init__(self, workers=2, per_user=1):
        import evals
        self.evals = evals
        self.queue = evals.local_queue()
        self.workers, self.per_user = workers, per_user
        self.stop = threading.Event()
        self.lock = None

    def acquire(self):
        self.lock = open(str(self.queue.path) + ".runner.lock", "a+")
        try: fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close(); self.lock = None
            raise RuntimeError("a local worker pool already owns this queue") from None

    def recover(self):
        """A restarted pool fails interrupted attempts after cleanup; queued jobs survive."""
        for ev in self.queue.active():
            if ev["status"] != "running": continue
            pid = ev.get("pid")
            if stop_process(pid, ev["id"]):
                for _ in range(30):
                    try: os.kill(pid, 0)
                    except ProcessLookupError: break
                    time.sleep(0.1)
                stop_process(pid, ev["id"], signal.SIGKILL)
                # Cleanup below also removes containers after their host command has exited.
            cleanup(ev["id"])
            ev = self.queue.update(ev["id"], status="failed", pid=None,
                                   error="local worker stopped before this attempt finished; submit a new evaluation to retry",
                                   finished=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            self.evals._save(ev)

    def execute(self, ev):
        eid = ev["id"]
        p = None
        error = None
        rc = None
        try:
            env = dict(os.environ, HR_EVENTS=self.evals._path(eid, "events.jsonl"),
                       HR_ISOLATED_RUN="1", HR_LOCAL_EVAL_ID=eid, HR_EVALS="local-queue")
            env.pop("HR_GIT_TOKEN", None)
            if ev.get("installation"):
                import auth
                env["HR_GIT_TOKEN"] = auth.clone_token(ev["installation"])[0]
            os.makedirs(self.evals._path(eid), exist_ok=True)
            if not self.queue.get(eid)["cancelled"]:
                with open(self.evals._path(eid, "console.log"), "wb") as log:
                    p = subprocess.Popen(["bash", os.path.join(self.evals.HERE, "run.sh"), ev["url"],
                                          "--taskset", ev["taskset"], "--tasks", ev["task"], "--run-id", eid],
                                         cwd=self.evals.HERE, env=env, stdin=subprocess.DEVNULL,
                                         stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                ev = self.queue.update(eid, pid=p.pid)
                self.evals._save(ev)
                interrupted_at = None
                published_at = 0
                while p.poll() is None:
                    current = self.queue.get(eid)
                    if self.stop.is_set() or current["cancelled"]:
                        if interrupted_at is None:
                            os.killpg(p.pid, signal.SIGTERM)
                            interrupted_at = time.monotonic()
                            if self.stop.is_set(): error = "local worker was stopped"
                        elif time.monotonic() - interrupted_at > 5:
                            try: os.killpg(p.pid, signal.SIGKILL)
                            except ProcessLookupError: pass
                    if time.monotonic() - published_at > 2:
                        self.evals._save(current)
                        published_at = time.monotonic()
                    self.stop.wait(0.2) if not self.stop.is_set() else time.sleep(0.1)
                rc = p.wait()
        except Exception as e:
            error = str(e)
        finally:
            if p is not None and p.poll() is None:
                try: os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                rc = p.wait()
            try: cleanup(eid)
            except Exception as e: error = f"{error + '; ' if error else ''}cleanup failed: {e}"

        finished = False
        try:
            result = json.loads(Path(self.evals.RUNS, ev["run"], "run.json").read_text())
            finished = bool(result.get("finished"))
        except (OSError, ValueError): pass
        ev = self.queue.update(eid, pid=None, rc=rc, status="done" if finished and not error else "failed",
                               error=error or (None if finished else self.evals._last_error(eid) or f"run.sh exited with {rc}"),
                               finished=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        self.evals._save(ev)
        if ev["status"] == "done": self.evals.after_run(ev)
        print(f"{eid}: {ev['status']} ({ev['user']})", flush=True)

    def worker(self, index):
        while not self.stop.is_set():
            ev = self.queue.claim(f"local-{index}", self.per_user)
            if ev is None:
                self.stop.wait(0.25)
                continue
            print(f"{ev['id']}: running for {ev['user']} on worker {index}", flush=True)
            self.execute(ev)

    def run(self):
        self.acquire()
        try:
            self.recover()
            print(f"Local queue: {self.queue.path}; workers={self.workers}; per-user={self.per_user}", flush=True)
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as pool:
                futures = [pool.submit(self.worker, i + 1) for i in range(self.workers)]
                while not self.stop.wait(0.25):
                    for future in futures:
                        if future.done():
                            self.stop.set()
                            future.result()
                for future in futures: future.result()
        finally:
            if self.lock: self.lock.close()
