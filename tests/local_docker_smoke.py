#!/usr/bin/env python3
"""Opt-in: exercise HTTP → durable queue → two workers → real Docker → verifier.

Uses an isolated copy, a local Git fixture, a local fake model endpoint, and a
temporary table in DynamoDB Local. It makes no GitHub, Claude, or model-provider calls.
Docker may download Python dependencies while building the recording proxy.
"""
import concurrent.futures
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]


def command(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs).stdout.strip()


def write(path, text, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if executable: path.chmod(0o755)


def wait_for(fn, timeout=240):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = fn()
        if result: return result
        time.sleep(0.2)
    raise AssertionError("timed out waiting for local evaluation state")


class Model(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        body = json.dumps({"id": "local-fixture", "model": "fixture", "object": "chat.completion",
                           "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                           "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *_): pass


def make_fixture():
    command(["docker", "info"])
    scratch = Path(tempfile.mkdtemp(prefix="hr-queue-smoke-", dir="/private/tmp" if Path("/private/tmp").exists() else None))
    print(f"Isolated test artifacts: {scratch}", flush=True)
    app, data = scratch / "app", scratch / "data"
    app.mkdir()
    for f in ("run.sh", "hr-local", "serve.py", "auth.py", "evals.py", "proxy.py", "policy.py"):
        shutil.copy2(ROOT / f, app / f)
    shutil.copytree(ROOT / "lib", app / "lib", ignore=shutil.ignore_patterns("__pycache__"))
    model = ThreadingHTTPServer(("0.0.0.0", 0), Model)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    source = scratch / "fixture"
    source.mkdir()
    write(source / "agent.py", '''import json, os, pathlib, socket, time, urllib.request
owner = socket.gethostname()
pathlib.Path("/app/owner").write_text(owner)
req = urllib.request.Request(os.environ["OPENAI_BASE_URL"] + "/chat/completions",
    data=json.dumps({"model":"fixture","messages":[{"role":"user","content":"hello"}]}).encode(),
    headers={"Content-Type":"application/json"})
with urllib.request.urlopen(req) as response: json.load(response)
pathlib.Path("/out/timing.json").write_text(json.dumps({"owner":owner,"started":time.time()}))
time.sleep(12)
print("fixture agent finished", flush=True)
''')
    real_git = shutil.which("git")
    command([real_git, "init", "-q", str(source)])
    command([real_git, "-C", str(source), "add", "."])
    command([real_git, "-C", str(source), "-c", "user.name=Local fixture", "-c", "user.email=fixture@localhost",
             "-c", "commit.gpgsign=false", "commit", "-qm", "fixture"])
    commit = command([real_git, "-C", str(source), "rev-parse", "HEAD"])
    binaries = scratch / "bin"
    write(binaries / "git", f'''#!{sys.executable}
import os,sys
args = [{str(source)!r} if a == "https://github.com/fixture/agent" else a for a in sys.argv[1:]]
os.execv({real_git!r}, [{real_git!r}, *args])
''', True)
    write(binaries / "claude", '#!/bin/sh\necho "Unexpected analyzer call in fixture" >&2\nexit 99\n', True)
    task = scratch / "tasks/datasets/aider_polyglot/polyglot_python_bowling"
    write(task / "task.toml", '[agent]\ntimeout_sec=180\n[verifier]\ntimeout_sec=30\n[environment]\ncpus=0.5\nmemory_mb=128\n')
    write(task / "instruction.md", 'Write your container identity and ask the model to say hello.\n')
    write(task / "environment/Dockerfile", 'FROM python:3.12-slim\nWORKDIR /app\n')
    write(task / "tests/test.sh", '''#!/bin/sh
set -eu
python3 -c 'import pathlib,socket; assert pathlib.Path("/app/owner").read_text() == socket.gethostname()'
echo 1 > /logs/verifier/reward.txt
echo '1 identity test passed'
''')
    recipes = scratch / "recipes"
    recipe = {"base_image": "python:3.12-slim", "dockerfile": "ARG BASE\nFROM ${BASE}\nCOPY . /opt/harness\n",
              "run_command": "python3 /opt/harness/agent.py", "check_command": "python3 -m py_compile /opt/harness/agent.py",
              "env": [{"name": "OPENAI_BASE_URL", "value": "$PROXY_URL/v1"}], "api_style": "openai", "summary": "Local fixture"}
    write(recipes / f"fixture-agent@{commit}.json", json.dumps(recipe))
    write(app / ".env", "# The smoke test supplies all settings through its environment.\n")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    table = "hr-queue-smoke-" + uuid.uuid4().hex[:12]
    env = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ["PATH"], HR_EVALS="local-queue",
               HR_LOCAL_USERS="1", HR_DATA_DIR=str(data), HR_RECIPE_DIR=str(recipes), HR_DDB="local",
               HR_DDB_ENDPOINT="http://127.0.0.1:8001", HR_TABLE=table, HR_RECOMMEND="off", HR_DAILY_CAP="0",
               HARBOR_TASKS=str(scratch / "tasks"), MODEL="openai/fixture", ROUTES="", AWS_REGION="us-west-2",
               AWS_PROFILE="", AWS_EC2_METADATA_DISABLED="true", OPENAI_API_KEY="fixture",
               OPENAI_BASE_URL=f"http://host.docker.internal:{model.server_port}/v1", HR_PLATFORM="linux/amd64",
               GITHUB_CLIENT_ID="", GITHUB_CLIENT_SECRET="", GITHUB_APP_ID="", GITHUB_APP_KEY="")
    return scratch, app, data, model, port, table, env


def main():
    scratch, app, data, model, port, table, env = make_fixture()
    command([sys.executable, str(app / "lib/store.py"), "table"], env=env)
    api = worker = None
    jobs = []
    try:
        api = subprocess.Popen([sys.executable, str(app / "serve.py"), "--port", str(port), "--dist", str(ROOT / "web/dist")],
                               env=env, stdout=open(scratch / "api.log", "w"), stderr=subprocess.STDOUT)

        def request(path, user="alice", body=None):
            req = urllib.request.Request(f"http://127.0.0.1:{port}" + path,
                                         data=json.dumps(body).encode() if body is not None else None,
                                         headers={"Cookie": f"hr_local_user={user}", "Content-Type": "application/json"})
            try: response = urllib.request.urlopen(req, timeout=20)
            except urllib.error.HTTPError as e: response = e
            with response: return response.status, json.load(response)

        def ready():
            try: return request("/api/me")[0] == 200
            except OSError: return False
        wait_for(ready, 15)
        def submit(user):
            status, body = request("/api/evals", user, {"repo": "fixture/agent", "taskset": "aider_polyglot", "task": "polyglot_python_bowling"})
            assert status == 201, body
            return body["eval"]
        # Simultaneous users, including the very same repository, receive separate jobs.
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            jobs = list(pool.map(submit, ["alice", "alice", "bob", "charlie"]))
        waiting = submit("alice"); jobs.append(waiting)
        assert request(f"/api/evals/{waiting['id']}/cancel", "alice", {})[0] == 200
        assert len({j["id"] for j in jobs}) == len(jobs)
        bob = next(j for j in jobs if j["user"] == "bob")
        assert request(f"/api/evals/{bob['id']}/cancel", "alice", {})[0] == 403
        # Restart HTTP before execution; accepted jobs must remain queued.
        api.terminate(); api.wait(timeout=10)
        api = subprocess.Popen([sys.executable, str(app / "serve.py"), "--port", str(port), "--dist", str(ROOT / "web/dist")],
                               env=env, stdout=open(scratch / "api-restarted.log", "w"), stderr=subprocess.STDOUT)
        wait_for(ready, 15)
        assert request(f"/api/evals/{bob['id']}", "bob")[1]["eval"]["status"] == "queued"
        worker = subprocess.Popen([sys.executable, str(app / "hr-local"), "--workers", "2", "--per-user", "1"],
                                  env=env, stdout=open(scratch / "workers.log", "w"), stderr=subprocess.STDOUT)
        max_running = max_sandboxes = 0
        cancelled_bob = False
        deadline = time.monotonic() + 360
        while time.monotonic() < deadline:
            assert worker.poll() is None, (scratch / "workers.log").read_text()
            states = [request(f"/api/evals/{j['id']}", j["user"])[1]["eval"] for j in jobs]
            running = [j for j in states if j["status"] == "running"]
            max_running = max(max_running, len(running))
            assert len(running) <= 2, states
            assert len([j for j in running if j["user"] == "alice"]) <= 1, states
            sandboxes = command(["docker", "ps", "--filter", "label=hr.evaluation", "--format", "{{.Names}}"])
            count = sum(f"hr-run-{j['run']}" in sandboxes.splitlines() for j in jobs)
            max_sandboxes = max(max_sandboxes, count)
            if not cancelled_bob and (data / "runs" / bob["run"] / "timing.json").exists():
                assert request(f"/api/evals/{bob['id']}/cancel", "bob", {})[0] == 200
                cancelled_bob = True
            if all(j["status"] in ("done", "failed", "cancelled") for j in states): break
            time.sleep(0.3)
        else: raise AssertionError("Docker evaluations did not finish")
        assert cancelled_bob and max_running == 2 and max_sandboxes == 2, (states, max_running, max_sandboxes)
        assert sum(j["status"] == "done" for j in states) == 3, states
        assert sum(j["status"] == "cancelled" for j in states) == 2, states
        owners = set()
        for job in states:
            if job["status"] != "done": continue
            folder = data / "runs" / job["run"]
            record = json.loads((folder / "run.json").read_text())
            assert record["reward"] == 1, record
            assert record["calls"] == 1 and record["errors"] == 0, record
            owners.add(json.loads((folder / "timing.json").read_text())["owner"])
        assert len(owners) == 3, "sandboxes shared a container identity"
        extra_pool = subprocess.run([sys.executable, str(app / "hr-local"), "--workers", "10"], env=env,
                                    capture_output=True, text=True, timeout=10)
        assert extra_pool.returncode != 0 and "already owns" in extra_pool.stderr, extra_pool
        worker.terminate(); worker.wait(timeout=20)
        interrupted = submit("alice"); jobs.append(interrupted)
        survives = submit("bob"); jobs.append(survives)
        worker = subprocess.Popen([sys.executable, str(app / "hr-local"), "--workers", "1"], env=env,
                                  stdout=open(scratch / "workers-before-crash.log", "w"), stderr=subprocess.STDOUT)
        wait_for(lambda: (data / "runs" / interrupted["run"] / "timing.json").exists())
        worker.kill(); worker.wait(timeout=10)
        worker = subprocess.Popen([sys.executable, str(app / "hr-local"), "--workers", "1"], env=env,
                                  stdout=open(scratch / "workers-after-crash.log", "w"), stderr=subprocess.STDOUT)
        wait_for(lambda: request(f"/api/evals/{interrupted['id']}", "alice")[1]["eval"]["status"] == "failed")
        wait_for(lambda: request(f"/api/evals/{survives['id']}", "bob")[1]["eval"]["status"] in ("done", "failed"))
        survived = request(f"/api/evals/{survives['id']}", "bob")[1]
        assert survived["eval"]["status"] == "done" and survived["result"]["reward"] == 1, survived
        print("PASS: parallel users; unique same-repo jobs; durable HTTP restart; 2 concurrent Docker sandboxes; per-user limit; queued/running cancellation; 4 isolated verifier passes; local proxy recording; worker crash recovery; singleton pool.", flush=True)
    finally:
        for process in (worker, api):
            if process and process.poll() is None:
                process.terminate()
                try: process.wait(timeout=20)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
        model.shutdown(); model.server_close()
        for job in jobs:
            for kind in ("container", "network", "image"):
                ids = command(["docker", kind, "ls", "-q", "--filter", f"label=hr.evaluation={job['id']}", *(["-a"] if kind == "container" else [])]).split()
                if ids: subprocess.run(["docker", kind, "rm", *(["-f"] if kind != "network" else []), *set(ids)], capture_output=True)
        command([sys.executable, "-c", "import sys; sys.path.insert(0,sys.argv[1]); import ddb; ddb.call('DeleteTable', {'TableName':ddb.table()})", str(app / "lib")], env=env)


if __name__ == "__main__": main()
