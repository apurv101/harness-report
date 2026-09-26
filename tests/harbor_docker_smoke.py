"""Real Docker/Harbor smoke: task routing, sidecar model calls, isolation, grading and cancellation.

Uses only a local fake model; no provider credentials or paid calls. Run explicitly:
    python3 tests/harbor_docker_smoke.py
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

from local_docker_smoke import make_fixture, command, write, wait_for


def main():
    scratch, app, data, model, _, _, env = make_fixture()
    task = scratch / "tasks/datasets/aider_polyglot/polyglot_python_bowling"
    source = scratch / "fixture"
    write(source / "agent.py", '''import json,os,pathlib,time,urllib.request
assert not pathlib.Path('/tests/test.sh').exists(), 'tests leaked before verification'
url=os.environ['OPENAI_BASE_URL']+'/chat/completions'
req=urllib.request.Request(url,data=json.dumps({'model':'fixture','messages':[{'role':'user','content':'hello'}]}).encode(),headers={'Content-Type':'application/json'})
with urllib.request.urlopen(req) as r: json.load(r)
with urllib.request.urlopen('http://fixture-counter:8000/visit') as r: data=json.load(r)
assert data['count']==1, 'state leaked between trials'
pathlib.Path('/app/answer.json').write_text(json.dumps(data))
pathlib.Path('/out/timing.json').write_text(json.dumps({'started':time.time()}))
time.sleep(8)
print('agent reached sidecar',flush=True)
''')
    command(["git", "-C", str(source), "add", "."])
    command(["git", "-C", str(source), "-c", "user.name=Fixture", "-c", "user.email=test@localhost",
             "-c", "commit.gpgsign=false", "commit", "-qm", "compose fixture"])
    commit = command(["git", "-C", str(source), "rev-parse", "HEAD"])
    recipe = json.loads(next((scratch / "recipes").glob("*.json")).read_text())
    write(scratch / "recipes" / f"fixture-agent@{commit}.json", json.dumps(recipe))
    write(task / "task.toml", '[agent]\ntimeout_sec=60\n[verifier]\ntimeout_sec=30\n[environment]\ncpus=1\nmemory_mb=256\n')
    write(task / "environment/counter/Dockerfile", 'FROM python:3.12-slim\nCOPY server.py /server.py\nCMD ["python3","/server.py"]\n')
    write(task / "environment/counter/server.py", '''import json,os,pathlib,urllib.request
from http.server import BaseHTTPRequestHandler,HTTPServer
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  state=pathlib.Path('/state/count')
  n=int(state.read_text()) if state.exists() else 0
  if self.path=='/visit':
   n+=1;state.write_text(str(n))
   req=urllib.request.Request(os.environ['OPENAI_BASE_URL']+'/chat/completions',data=json.dumps({'model':'fixture','messages':[{'role':'user','content':'sidecar hello'}]}).encode(),headers={'Content-Type':'application/json'})
   with urllib.request.urlopen(req) as r:json.load(r)
  body=json.dumps({'count':n,'hostname':os.uname().nodename}).encode()
  self.send_response(200);self.end_headers();self.wfile.write(body)
HTTPServer(('0.0.0.0',8000),Handler).serve_forever()
''')
    write(task / "environment/docker-compose.yaml", '''services:
  main:
    depends_on:
      counter:
        condition: service_healthy
  counter:
    build: ./counter
    container_name: fixture-counter
    environment:
      OPENAI_API_KEY: ${OPENAI_API_KEY:-}
    volumes:
      - counter_state:/state
    healthcheck:
      test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 1s
      timeout: 2s
      retries: 10
volumes:
  counter_state: {}
''')
    write(task / "tests/test.sh", '''#!/bin/sh
set -eu
python3 - <<'PY'
import json,pathlib,urllib.request
a=json.loads(pathlib.Path('/app/answer.json').read_text())
with urllib.request.urlopen('http://counter:8000/state') as r:b=json.load(r)
assert a==b and a['count']==1, (a,b)
pathlib.Path('/logs/verifier/reward.json').write_text(json.dumps({'reward':1,'sidecar_count':1}))
print('1 sidecar state test passed')
PY
''')
    env.update(HR_DDB="", HR_DDB_ENDPOINT="", HR_TABLE="", HR_ISOLATED_RUN="1")
    jobs = []
    def launch(n):
        eid = f"hb-smoke-{uuid.uuid4().hex[:12]}-{n}"
        run = eid + "-polyglot_python_bowling"
        log = scratch / f"{eid}.log"
        with log.open("w") as stream:
            p = subprocess.Popen(["bash", str(app / "run.sh"), "https://github.com/fixture/agent", "--taskset", "aider_polyglot",
                "--tasks", "polyglot_python_bowling", "--run-id", eid], env={**env,"HR_LOCAL_EVAL_ID":eid},
                stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        job = (eid, run, p, log)
        jobs.append(job)
        return job
    try:
        first, second = launch(1), launch(2)
        for eid, run, p, log in (first, second):
            assert p.wait(timeout=300)==0, log.read_text()
            out=data / "runs" / run
            report=json.loads((out / "run.json").read_text())
            assert report['reward']==1 and report['calls']==2, report
            detail=json.loads((out / "harbor-result.json").read_text())
            assert detail['rewards']=={'reward':1,'sidecar_count':1},detail
            assert not command(['docker','ps','-aq','--filter',f'label=hr.evaluation={eid}']),eid
            assert not command(['docker','volume','ls','-q','--filter',f'label=hr.evaluation={eid}']),eid
        a,b=[json.loads((data/'runs'/j[1]/'harbor-result.json').read_text()) for j in (first,second)]
        assert a['trial']['id']!=b['trial']['id']
        eid,run,p,log=launch('cancel')
        wait_for(lambda:(data/'runs'/run/'timing.json').exists() or p.poll() is not None,240)
        assert p.poll() is None,log.read_text()
        os.killpg(p.pid,signal.SIGTERM)
        p.wait(timeout=60)
        sys.path.insert(0,str(app/'lib'))
        from localrunner import cleanup
        cleanup(eid)
        for kind in ('container','network','volume'):
            assert not command(['docker',kind,'ls','-q','--filter',f'label=hr.evaluation={eid}',*(['-a'] if kind=='container' else [])]),kind
        # A failed dependency healthcheck must leave neither a passing reward nor a partial stack.
        compose=task/'environment/docker-compose.yaml'
        compose.write_text(compose.read_text().replace("import urllib.request; urllib.request.urlopen('http://localhost:8000/health')", "raise SystemExit(1)").replace('retries: 10','retries: 1'))
        eid,run,p,log=launch('unhealthy')
        assert p.wait(timeout=120)!=0,log.read_text()
        report=json.loads((data/'runs'/run/'harbor-result.json').read_text())
        assert report['reward'] is None and report['error'],report
        assert not command(['docker','ps','-aq','--filter',f'label=hr.evaluation={eid}']),eid
        assert not command(['docker','volume','ls','-q','--filter',f'label=hr.evaluation={eid}']),eid
        print('PASS: two isolated Harbor Compose trials; agent + sidecar calls recorded; hidden tests; JSON rewards; cancellation and failed-start cleanup.',flush=True)
    finally:
        sys.path.insert(0,str(app/'lib'))
        from localrunner import cleanup
        for eid,run,p,log in jobs:
            if p.poll() is None:
                os.killpg(p.pid,signal.SIGTERM)
                try:p.wait(timeout=60)
                except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
            cleanup(eid)
        model.shutdown()


if __name__=='__main__':main()
