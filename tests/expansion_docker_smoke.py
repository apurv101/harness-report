"""Real expansion-adapter smoke; run after building the selected task's base image.

Uses deterministic harness fixtures and no model API calls.
python3 tests/expansion_docker_smoke.py cooperbench|tau3-bench
"""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

REPO = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get('HARBOR_TASKS', Path.home() / 'Desktop/harbor-tasks'))


def main(taskset):
    name = 'cb-chi-t26-f1-2' if taskset == 'cooperbench' else 'tau3-retail-0'
    task = ROOT / ('datasets/cooperbench' if taskset == 'cooperbench' else 'tau3-bench') / name
    out = REPO / 'work/expansion' / taskset / name / ('bridge-' + uuid.uuid4().hex[:8]); out.mkdir(parents=True)
    wrapper = out / 'fixture.sh'
    if taskset == 'cooperbench':
        patch = base64.b64encode((task / 'solution/combined.patch').read_bytes()).decode()
        wrapper.write_text('''#!/bin/bash
set -eu
cd "$1"
test ! -f /tests/test.sh
test ! -d /solution
grep -q "Feature\\|Title" "$2"
other=agent1; [ "$AGENT_ID" = agent1 ] && other=agent2
send_message "$other" "fixture-ready"
for i in $(seq 1 30); do
  check_messages >> /out/messages.log
  grep -q fixture-ready /out/messages.log && break
  sleep 1
done
grep -q fixture-ready /out/messages.log
python3 - <<'PY'
import base64,subprocess
subprocess.run(['git','apply','--allow-empty','-'],input=base64.b64decode(''' + repr(patch) + '''),check=True)
PY
echo "$AGENT_ID" > /out/selected-harness-ran
''')
    else:
        wrapper.write_text('''#!/bin/bash
set -eu
grep -q hr-mcp "$2"
hr-mcp tau3-runtime list > /out/tools.json
hr-mcp tau3-runtime call get_runtime_status > /out/status.json
python3 - <<'PY'
import json
tools=json.load(open('/out/tools.json'))['tools']
assert {'start_conversation','get_order_details','exchange_delivered_order_items'} <= {t['name'] for t in tools}
assert not json.load(open('/out/status.json')).get('isError')
PY
''')
    (out / 'recipe.json').write_text('{"env":[]}')
    net = 'hr-expansion-fixture-' + uuid.uuid4().hex[:10]
    subprocess.run(['docker','network','create',net],check=True,capture_output=True)
    try:
        with (out / 'console.log').open('w') as log:
            result = subprocess.run([sys.executable,str(REPO/'lib/harbor_python.py'),'run','--task',str(task),
                '--image',f'hr-task/{taskset}:{name}','--out',str(out),'--work',str(out/'work'),
                '--workdir','/workspace/repo' if taskset == 'cooperbench' else '/app', '--platform','linux/amd64',
                '--network',net,'--verify-network',net,'--egress','open', '--recipe',str(out/'recipe.json'),'--wrapper',str(wrapper)],
                stdout=log,stderr=subprocess.STDOUT,timeout=2400)
        record = json.loads((out/'harbor-result.json').read_text())
        assert result.returncode == 0 and not record['error'], record.get('error')
        assert record['rc'] == 0, record
        assert record['reward'] == (1 if taskset == 'cooperbench' else 0), record['reward']
        if taskset == 'cooperbench':
            for agent in ('agent1','agent2'):
                assert (out/'agent'/agent/'selected-harness-ran').read_text().strip() == agent
        evidence = {'taskset': taskset, 'task': name, 'check': 'selected-harness-bridge', 'passed': True,
                    'reward': record['reward'], 'logs': str(out.relative_to(REPO)),
                    'at': time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
        with (REPO/'catalog/expansion-validation.jsonl').open('a') as f: f.write(json.dumps(evidence)+'\n')
        print(json.dumps(evidence))
    finally:
        subprocess.run(['docker','network','rm',net],capture_output=True)


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in ('cooperbench','tau3-bench'):
        raise SystemExit(__doc__)
    main(sys.argv[1])
