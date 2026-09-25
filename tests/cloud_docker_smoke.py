#!/usr/bin/env python3
"""Opt-in AWS integration: temporary SQS FIFO + DynamoDB, two local Docker workers.

Uses AWS_PROFILE=operator unless explicitly overridden. No cloud model calls or
EC2 launches. Removes only its own temporary queue/table and labelled containers.
"""
import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

from local_docker_smoke import ROOT, command, make_fixture, wait_for, write


def main():
    profile = os.environ.get("AWS_PROFILE") or "operator"
    scratch, app, data, model, port, _, env = make_fixture()
    name = "hr-cloud-smoke-" + uuid.uuid4().hex[:12]
    shutil.copy2(ROOT / "hr-agentd", app / "hr-agentd")
    env.update(AWS_PROFILE=profile, HR_EVALS="queue", HR_LOCAL_USERS="0", HR_DDB="", HR_DDB_ENDPOINT="",
               HR_TABLE=name, HR_RUN_PROFILE="", HR_RUNNER_EC2="0", HR_ASG_NAME="", HR_MODEL_ROLE_ARN="",
               HR_RUNS_BUCKET="", HR_RECIPES_BUCKET="", HR_TASKS_BUCKET="", HR_QUEUE_URL="", HR_SCALER_FUNCTION="")
    # Fake sessions exist only in this temporary test server, never in the deployed GitHub flow.
    write(app / "fixture_server.py", '''from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer
import serve, sys
class Fixture(serve.H):
    def session(self):
        c = SimpleCookie(self.headers.get('Cookie') or '')
        user = c.get('fixture_user')
        return {'login':user.value, 'local':True} if user and user.value in ('alice','bob','charlie') else None
ThreadingHTTPServer(('127.0.0.1', int(sys.argv[1])), Fixture).serve_forever()
''')
    api, workers, jobs, queue_url = None, [], [], None
    created_table = False
    os.environ.update(env)
    sys.path[:0] = [str(app), str(app / "lib")]
    import cloudqueue, ddb, evals, leases
    try:
        queue_url = json.loads(command(["aws", "sqs", "create-queue", "--queue-name", name + ".fifo", "--region", "us-west-2",
            "--attributes", json.dumps({"FifoQueue":"true", "VisibilityTimeout":"30", "ReceiveMessageWaitTimeSeconds":"1"}),
            "--tags", "Purpose=harness-report-smoke", "--output", "json"], env=env))["QueueUrl"]
        env["HR_QUEUE_URL"] = os.environ["HR_QUEUE_URL"] = queue_url
        command([sys.executable, str(app / "lib/store.py"), "table"], env=env); created_table = True
        print(f"Temporary AWS resources: {name} (profile {profile})", flush=True)
        # Exercise real transactions, not a mock of DynamoDB's condition evaluator.
        def capped(n):
            ev = evals._record("fixture/agent", evals._eid("fixture/agent"), "cap-test", "queued")
            try: return cloudqueue.enqueue(ev, daily_cap=3)
            except cloudqueue.Limit: return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            accepted = [e for e in pool.map(capped, range(12)) if e]
        assert len(accepted) == 3, accepted
        cloudqueue.cancel(accepted[0]["id"])
        replacement = capped(20)
        assert replacement, "cancelled submission did not return the daily slot"
        claim_target = accepted[1]["id"]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            claims = [e for e in pool.map(lambda n: cloudqueue.claim(claim_target, str(n)), range(8)) if e]
        assert len(claims) == 1, claims
        cloudqueue.cancel(claim_target)
        assert cloudqueue.update(claim_target, {"status":"done"}, token=claims[0]["claim"])["status"] == "cancelled"
        try: cloudqueue.update(claim_target, {"status":"done"}, token=claims[0]["claim"])
        except cloudqueue.LostLease: pass
        else: raise AssertionError("stale worker was allowed to publish")
        crashed = accepted[2]["id"]
        claim = cloudqueue.claim(crashed, "dead-worker")
        cloudqueue.update(crashed, {"lease_until": int(time.time()) - 1}, token=claim["claim"])
        assert cloudqueue.expire(crashed)["status"] == "failed"
        assert {e["id"] for e in cloudqueue.active()} == {replacement["id"]}
        cloudqueue.cancel(replacement["id"])
        assert not cloudqueue.active(), "terminal jobs must leave the scheduling index"

        def request(path, user="alice", body=None):
            req = urllib.request.Request(f"http://127.0.0.1:{port}" + path,
                data=json.dumps(body).encode() if body is not None else None,
                headers={"Cookie":f"fixture_user={user}", "Content-Type":"application/json"})
            try: response = urllib.request.urlopen(req, timeout=30)
            except urllib.error.HTTPError as e: response = e
            with response: return response.status, json.load(response)
        api = subprocess.Popen([sys.executable, str(app / "fixture_server.py"), str(port)], env=env,
                               stdout=open(scratch / "cloud-api.log", "w"), stderr=subprocess.STDOUT)
        def ready():
            try: return request("/api/me")[0] == 200
            except OSError: return False
        wait_for(ready, 20)
        for user in ("alice", "alice", "bob", "charlie"):
            status, result = request("/api/evals", user, {"repo":"fixture/agent", "taskset":"aider_polyglot", "task":"polyglot_python_bowling"})
            assert status == 201, result
            jobs.append(result["eval"])
        assert len(request("/api/evals", "alice")[1]["evals"]) == 2
        assert request(f"/api/evals/{jobs[0]['id']}", "bob")[0] == 403
        assert request(f"/api/evals/{jobs[0]['id']}/cancel", "bob", {})[0] == 403
        waiting = jobs[-1]
        request(f"/api/evals/{waiting['id']}/cancel", "charlie", {})
        assert {e["user"] for e in cloudqueue.active()} == {"alice", "bob"}
        api.terminate(); api.wait(timeout=10)
        api = subprocess.Popen([sys.executable, str(app / "fixture_server.py"), str(port)], env=env,
                               stdout=open(scratch / "cloud-api-restarted.log", "w"), stderr=subprocess.STDOUT)
        wait_for(ready, 20)
        for n in range(2):
            workers.append(subprocess.Popen([sys.executable, str(app / "hr-agentd")], env={**env, "HR_EVALS":"on"},
                stdout=open(scratch / f"cloud-worker-{n}.log", "w"), stderr=subprocess.STDOUT))
        max_sandboxes = 0
        cancelled = False
        deadline = time.monotonic() + 420
        while time.monotonic() < deadline:
            states = [cloudqueue.get(j["id"]) for j in jobs]
            active = [j for j in states if j["status"] == "running"]
            assert len(active) <= 2 and sum(j["user"] == "alice" for j in active) <= 1, states
            names = command(["docker", "ps", "--filter", "label=hr.evaluation", "--format", "{{.Names}}"])
            max_sandboxes = max(max_sandboxes, sum(f"hr-run-{j['run']}" in names.splitlines() for j in jobs))
            bob = jobs[2]
            if not cancelled and (data / "runs" / bob["run"] / "timing.json").exists():
                request(f"/api/evals/{bob['id']}/cancel", "bob", {}); cancelled = True
            if all(j["status"] in ("done", "failed", "cancelled") for j in states): break
            time.sleep(0.4)
        else: raise AssertionError("cloud jobs did not settle")
        assert max_sandboxes == 2 and cancelled, (states, max_sandboxes)
        assert [j["status"] for j in states] == ["done", "done", "cancelled", "cancelled"], states
        assert not cloudqueue.active(), "completed jobs would incorrectly keep EC2 capacity running"
        identities = set()
        for job in states[:2]:
            result = request(f"/api/evals/{job['id']}")[1]
            assert result["result"]["reward"] == 1 and result["result"]["calls"] == 1, result
            identities.add(json.loads((data / "runs" / job["run"] / "timing.json").read_text())["owner"])
        assert len(identities) == 2
        print("PASS: real AWS FIFO/DynamoDB; atomic limits/claims; stale-worker fencing; expiry; owner checks; HTTP restart; two Docker sandboxes; per-user serialization; cancellation; verified results.", flush=True)
    finally:
        for process in [*workers, api]:
            if process and process.poll() is None:
                process.terminate()
                try: process.wait(timeout=35)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
        model.shutdown(); model.server_close()
        for job in jobs:
            for kind in ("container", "network", "image"):
                ids = command(["docker", kind, "ls", "-q", "--filter", f"label=hr.evaluation={job['id']}", *(["-a"] if kind == "container" else [])]).split()
                if ids: subprocess.run(["docker", kind, "rm", *(["-f"] if kind != "network" else []), *set(ids)], capture_output=True)
        if queue_url: command(["aws", "sqs", "delete-queue", "--queue-url", queue_url, "--region", "us-west-2"], env=env)
        if created_table: ddb.call("DeleteTable", {"TableName": name})
        print(f"Removed temporary AWS resources; diagnostic logs: {scratch}", flush=True)


if __name__ == "__main__": main()
