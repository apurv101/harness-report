"""Explicit Docker negative controls for taskset/task arguments; uses original task graders."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tomllib
import uuid

REPO = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get('HARBOR_TASKS', Path.home() / 'Desktop/harbor-tasks'))
OUT = REPO / 'work/expansion'

def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], text=True, check=True, **kwargs)

def check(pair):
    ts, name = pair.split('/', 1)
    task = next(p / ts / name for p in [ROOT/'datasets', ROOT/'hub-datasets', ROOT] if (p/ts/name/'task.toml').exists())
    cfg = tomllib.loads((task/'task.toml').read_text())
    out = OUT / ts / name / ('nop-' + uuid.uuid4().hex[:8])
    out.mkdir(parents=True)
    image = f'hr-task/{ts}:{name}'
    if subprocess.run(['docker','image','inspect',image], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        image = cfg.get('environment',{}).get('docker_image', image)
    cname = 'hr-expand-nop-' + uuid.uuid4().hex[:12]
    start = time.time()
    record = {'taskset': ts, 'task': name, 'check': 'empty-submission', 'platform': 'linux/amd64', 'logs': str(out.relative_to(REPO))}
    try:
        working = run(['docker','image','inspect','-f','{{.Config.WorkingDir}}',image], capture_output=True).stdout.strip() or '/app'
        compose = any((task/'environment'/f).exists() for f in ['docker-compose.yaml','docker-compose.yml','compose.yaml','compose.yml'])
        if compose:
            recipe = out/'recipe.json'; recipe.write_text(json.dumps({'env': []}))
            wrapper = out/'nop.sh'; wrapper.write_text('#!/bin/bash\nexit 0\n')
            network = cname
            run(['docker','network','create',network], stdout=subprocess.DEVNULL)
            try:
                with (out/'console.log').open('w') as log:
                    proc = subprocess.run(['python3',str(REPO/'lib/harbor_python.py'),'run','--task',str(task),'--image',image,
                        '--out',str(out),'--work',str(out/'work'),'--workdir',working,'--platform','linux/amd64',
                        '--network',network,'--verify-network',network,'--egress','open','--recipe',str(recipe),'--wrapper',str(wrapper)],
                        stdout=log, stderr=subprocess.STDOUT, timeout=2400)
                record['rc'] = proc.returncode
                result = json.loads((out/'harbor-result.json').read_text())
                record['reward'] = result.get('reward')
                if result.get('error'): record['error'] = result['error']
            finally:
                subprocess.run(['docker','network','rm',network], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            run(['docker','run','-d','--platform','linux/amd64','--name',cname,'--label','hr.expansion=2026-09-25',
                 '-w',working,'-e','TEST_DIR=/tests',image,'sleep','infinity'],stdout=subprocess.DEVNULL)
            run(['docker','exec',cname,'mkdir','-p','/logs/verifier','/logs/agent','/tests'])
            run(['docker','cp',str(task/'tests')+'/.',cname+':/tests/'], stdout=subprocess.DEVNULL)
            timeout=int(cfg.get('verifier',{}).get('timeout_sec',1800))
            with (out/'verifier.log').open('w') as log:
                result=subprocess.run(['docker','exec','-w',working,cname,'bash','-lc','bash /tests/test.sh'],stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
            record['rc']=result.returncode
            run(['docker','cp',cname+':/logs/verifier/.',str(out)],stdout=subprocess.DEVNULL)
            reward_path=out/'reward.txt'
            record['reward']=float(reward_path.read_text().strip()) if reward_path.exists() else None
    except Exception as exc:
        record['error']=str(exc)
        record.setdefault('reward',None)
    finally:
        subprocess.run(['docker','rm','-f',cname],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    record['seconds']=round(time.time()-start)
    record['at']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
    record['passed']=record.get('reward')==0 and not record.get('error')
    (out/'check.json').write_text(json.dumps(record,indent=2)+'\n')
    return record

failed = False
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    for record in pool.map(check,sys.argv[1:]):
        failed |= not record['passed']
        print(json.dumps(record),flush=True)
        with (REPO/'catalog/expansion-validation.jsonl').open('a') as f:
            f.write(json.dumps(record)+'\n')

sys.exit(1 if failed else 0)
