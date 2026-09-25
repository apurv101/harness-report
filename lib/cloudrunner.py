"""SQS worker using the same isolated run.sh pipeline as the local pool."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import threading
import time
import urllib.request

import cloudqueue
import ddb
import evals
import leases
import store
from localrunner import cleanup

STOP = threading.Event()
PUBLISH_LOCK = threading.Lock()
VISIBILITY = 900
WORKED = False


def log(message): print(f"hr-agentd: {message}", flush=True)


def command(args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, timeout=300)


def protect_instance(protected):
    if not os.environ.get("HR_ASG_NAME"): return
    import boto3
    req = urllib.request.Request("http://169.254.169.254/latest/api/token", method="PUT",
                                 headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"})
    with urllib.request.urlopen(req, timeout=5) as response: token = response.read().decode()
    req = urllib.request.Request("http://169.254.169.254/latest/meta-data/instance-id",
                                 headers={"X-aws-ec2-metadata-token": token})
    with urllib.request.urlopen(req, timeout=5) as response: instance = response.read().decode()
    boto3.client("autoscaling").set_instance_protection(InstanceIds=[instance],
        AutoScalingGroupName=os.environ["HR_ASG_NAME"], ProtectedFromScaleIn=protected)


def publish(ev):
    path = Path(evals._path(ev["id"], "eval.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with PUBLISH_LOCK:
        path.write_text(json.dumps(ev))
        store.publish_eval(ev["id"])


def prepare(ev):
    """Download only this task; the task corpus never has to fit on the root disk."""
    bucket = os.environ.get("HR_TASKS_BUCKET")
    if bucket:
        destination = Path(os.environ["HARBOR_TASKS"], "datasets", ev["taskset"], ev["task"])
        command(["aws", "s3", "sync", f"s3://{bucket}/tasks/{ev['taskset']}/{ev['task']}/", str(destination), "--only-show-errors"])
        if not (destination / "task.toml").is_file(): raise RuntimeError("task is missing from the runner task bucket")
    bucket = os.environ.get("HR_RECIPES_BUCKET")
    if bucket:
        command(["aws", "s3", "sync", f"s3://{bucket}/recipes/", str(Path(evals.HERE, "recipes")), "--only-show-errors"])


def model_credentials(eid):
    """Only the trusted proxy receives a renewable, model-only role session."""
    role = os.environ.get("HR_MODEL_ROLE_ARN")
    if not role: return None
    import boto3
    credentials = boto3.client("sts").assume_role(RoleArn=role, RoleSessionName=eid[:64], DurationSeconds=3600)["Credentials"]
    directory = Path(evals._path(eid), "model-credentials")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    token = {"Version": 1, "AccessKeyId": credentials["AccessKeyId"], "SecretAccessKey": credentials["SecretAccessKey"],
             "SessionToken": credentials["SessionToken"], "Expiration": credentials["Expiration"].isoformat()}
    temporary = directory / ".token.json"
    temporary.write_text(json.dumps(token)); temporary.chmod(0o600)
    temporary.replace(directory / "token.json")
    (directory / "config").write_text("[profile hr-model]\ncredential_process = cat /hr/aws/token.json\n")
    return str(directory)


def archive(ev):
    bucket = os.environ.get("HR_RUNS_BUCKET")
    if bucket:
        for source, prefix in ((Path(evals.RUNS, ev["run"]), "runs/" + ev["run"]),
                               (Path(evals._path(ev["id"])), "evals/" + ev["id"])):
            if source.is_dir():
                command(["aws", "s3", "sync", str(source), f"s3://{bucket}/{prefix}/", "--exclude", "model-credentials/*", "--only-show-errors"])
    bucket = os.environ.get("HR_RECIPES_BUCKET")
    if bucket:
        command(["aws", "s3", "sync", str(Path(evals.HERE, "recipes")), f"s3://{bucket}/recipes/", "--only-show-errors"])


def run(lease):
    global WORKED
    eid = (lease.get("body") or {}).get("eval")
    if not eid or not evals.EVAL_ID.fullmatch(eid): return True
    ev = cloudqueue.get(eid)
    if not ev:
        # Allows the old standard queue to be drained explicitly with this daemon during migration.
        old = store.eval_record(eid)
        if not old or old["status"] not in ("queued", "running"): return True
        if old["status"] == "running":
            raise RuntimeError("stop the legacy runner and settle its active attempt before migration")
        ev = cloudqueue.enqueue({**old, "installation": lease["body"].get("installation")}, daily_cap=0)
    if ev["status"] == "running":
        ev = cloudqueue.expire(eid)
        if ev["status"] == "running":
            leases.extend(lease["receipt"], max(1, min(VISIBILITY, int(ev["lease_until"] - time.time()) + 5)))
            return False
    if ev["status"] != "queued": return True
    protect_instance(True)
    ev = cloudqueue.claim(eid, socket.gethostname(), VISIBILITY)
    if not ev: return False
    WORKED = True
    token = ev["claim"]
    aborted, watching = threading.Event(), threading.Event()
    reason = []
    p = None
    started = time.monotonic()
    max_seconds = int(os.environ.get("HR_MAX_JOB_SECONDS", "7200"))

    def watch():
        renewed = credentials_at = time.monotonic()
        while not watching.wait(2):
            try:
                current = cloudqueue.get(eid)
                if not current or current.get("claim") != token or current["status"] != "running":
                    raise cloudqueue.LostLease(eid)
                if current.get("cancelled") or STOP.is_set():
                    reason.append("evaluation cancelled" if current.get("cancelled") else "worker stopped")
                    aborted.set(); return
                if time.monotonic() - started > max_seconds: raise RuntimeError("evaluation exceeded its wall-clock limit")
                if time.monotonic() - renewed > 60:
                    leases.extend(lease["receipt"], VISIBILITY)
                    current = cloudqueue.update(eid, {"lease_until": int(time.time()) + VISIBILITY}, token=token)
                    renewed = time.monotonic()
                if time.monotonic() - credentials_at > 600:
                    model_credentials(eid); credentials_at = time.monotonic()
                publish({**current, "live": evals.live(current)})
            except Exception as e:
                reason.append(f"worker lost contact with the job or queue: {e}")
                aborted.set(); return

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    rc, error = None, None
    try:
        prepare(ev)
        credentials_dir = model_credentials(eid)
        env = dict(os.environ, HR_EVENTS=evals._path(eid, "events.jsonl"), HR_ISOLATED_RUN="1", HR_LOCAL_EVAL_ID=eid)
        env.pop("HR_GIT_TOKEN", None)
        if credentials_dir: env["HR_PROXY_CREDENTIALS_DIR"] = credentials_dir
        if ev.get("installation"):
            import auth
            env["HR_GIT_TOKEN"] = auth.clone_token(ev["installation"])[0]
        if os.environ.get("HR_RUN_PROFILE"): env["AWS_PROFILE"] = os.environ["HR_RUN_PROFILE"]
        elif os.environ.get("HR_RUNNER_EC2") != "1": env.pop("AWS_PROFILE", None)
        if aborted.is_set() or STOP.is_set(): raise RuntimeError(reason[0] if reason else "worker stopped")
        publish(ev)
        with open(evals._path(eid, "console.log"), "wb") as output:
            p = subprocess.Popen(["bash", str(Path(evals.HERE, "run.sh")), ev["url"], "--taskset", ev["taskset"],
                                  "--tasks", ev["task"], "--run-id", eid], cwd=evals.HERE, env=env,
                                 stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        terminated = None
        while p.poll() is None:
            if aborted.is_set() or STOP.is_set():
                if terminated is None:
                    os.killpg(p.pid, signal.SIGTERM); terminated = time.monotonic()
                elif time.monotonic() - terminated > 5:
                    try: os.killpg(p.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
            time.sleep(0.2)
        rc = p.wait()
        if reason or STOP.is_set(): error = reason[0] if reason else "worker stopped"
    except Exception as e: error = str(e)
    finally:
        if p and p.poll() is None:
            try: os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            p.wait()
        try: cleanup(eid)
        except Exception as e: error = f"{error or ''}; cleanup failed: {e}"

    try:
        result_path = Path(evals.RUNS, ev["run"], "run.json")
        result = json.loads(result_path.read_text()) if result_path.exists() else {}
        if result:
            store.publish_run(str(result_path.parent), replace=True)
        archive(ev)
        if reason: error = reason[0]
        status = "done" if result.get("finished") and not error else "failed"
        if status == "failed" and not error: error = evals._last_error(eid) or f"run.sh exited with {rc}"
        watching.set(); watcher.join(timeout=30)
        ev = cloudqueue.update(eid, {"status": status, "rc": rc, "error": error, "finished": cloudqueue.stamp()}, token=token)
        publish(ev)
        # Run before the disposable VM exits; its clone is required for profiling.
        if ev["status"] == "done" and os.environ.get("HR_RECOMMEND") != "off":
            import recommend
            recommend.refresh(ev["harness"], src=str(Path(evals.DATA, "work", "jobs", eid, ev["harness"], "repo")))
        log(f"{eid}: {ev['status']}")
        return True
    except cloudqueue.LostLease:
        log(f"{eid}: lease lost; stopped without publishing a terminal state")
        return False
    except Exception as e:
        watching.set(); watcher.join(timeout=30)
        try:
            ev = cloudqueue.update(eid, {"status": "failed", "rc": rc, "error": f"could not publish result: {e}",
                                         "finished": cloudqueue.stamp()}, token=token)
            publish(ev)
            return True
        except cloudqueue.LostLease: return False
    finally:
        watching.set(); watcher.join(timeout=30)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--retire-after-job", action="store_true", help="exit after the first received job; EC2 service retires the VM")
    ap.add_argument("--idle-seconds", type=int, default=0, help="retire if no message arrives within this many seconds")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    if args.status:
        print(f"Queue: {leases.url()}\nDepth: {leases.depth()}\nStore: {ddb.target()}"); return
    if evals.QUEUED or evals.LOCAL_QUEUED: ap.error("the worker requires HR_EVALS=on")
    if not leases.configured(): ap.error("HR_QUEUE_URL is required")
    for sig in (signal.SIGTERM, signal.SIGINT): signal.signal(sig, lambda *_: STOP.set())
    log(f"consuming {leases.url()}")
    idle_since = time.monotonic()
    while not STOP.is_set():
        lease = None
        try:
            lease = leases.receive(wait=20, visibility=VISIBILITY)
            if lease and run(lease): leases.delete(lease["receipt"])
        except Exception as e:
            log(str(e))
            if not lease: STOP.wait(10)
        if args.once or (WORKED and args.retire_after_job): return
        if lease: idle_since = time.monotonic()
        if args.idle_seconds and time.monotonic() - idle_since >= args.idle_seconds: return
