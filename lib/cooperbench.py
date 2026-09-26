"""Run a selected harness in each CooperBench worker, retaining the task's grader."""
from pathlib import Path
import shutil


WORKER = r'''#!/bin/bash
set -eu
unset BASH_ENV MSWEA_AGENT_CLASS
cd /workspace/repo
BASE=$(git rev-parse HEAD)
mkdir -p /agent_output /out /logs/agent
finish() {
  rc=$?
  trap - EXIT
  git add -A && git diff --cached --binary "$BASE" > /agent_output/agent.patch || rc=1
  printf '%s\n' "$rc" > /agent_output/exit-code
  touch /agent_output/agent.done
  # Compose waits for running services; preserve completion separately.
  exec sleep infinity
}
trap finish EXIT
timeout -s TERM -k 10 "$AGENT_TIMEOUT" bash /hr-worker/run-harness /workspace/repo /hr-worker/instruction.md > /out/console.log 2>&1
'''

COORDINATOR = r'''#!/bin/bash
set -eu
while [ ! -f /shared/agent1/agent.done ] || [ ! -f /shared/agent2/agent.done ]; do sleep 1; done
rc=0
for agent in agent1 agent2; do
  code=$(cat /shared/$agent/exit-code)
  echo "$agent exited with status $code"
  [ "$code" = 0 ] || rc=$code
done
exit "$rc"
'''


def configure(config, *, task, work, out, image, wrapper, env, oracle):
    """Mutate only the staged Compose config; never change the downloaded grader."""
    services = config['services']
    if not {'main', 'agent1', 'agent2', 'redis'} <= services.keys():
        raise ValueError('Unsupported CooperBench service layout')
    bridge = work / 'cooperbench'
    bridge.mkdir()
    coordinator = bridge / 'coordinator.sh'
    coordinator.write_text(COORDINATOR)
    coordinator.chmod(0o755)
    for name in ('agent1', 'agent2'):
        service = services[name]
        if not any(v.get('target') == '/agent_output' for v in service.get('volumes', [])):
            raise ValueError('CooperBench worker has no patch output volume')
        service.pop('build', None)
        service['image'] = image
        service['pull_policy'] = 'never'
        service['working_dir'] = '/workspace/repo'
        service['command'] = []
        service['environment'].update(BASH_ENV='', MSWEA_AGENT_CLASS='')
        if oracle:
            # The reference solution is evaluated in main. No background model calls.
            service['entrypoint'] = ['sleep', 'infinity']
            continue
        if not wrapper:
            raise ValueError('CooperBench requires a harness launcher')
        assets = bridge / name
        assets.mkdir()
        shutil.copy2(wrapper, assets / 'run-harness')
        (assets / 'worker.sh').write_text(WORKER)
        teammate = 'agent2' if name == 'agent1' else 'agent1'
        prompt = (task / 'environment' / name / 'instruction.md').read_text()
        (assets / 'instruction.md').write_text(
            f'You are {name}, working concurrently with {teammate} in separate repository copies. '
            'Implement your assigned feature. Your changes will be merged and tested together. '
            f'Coordinate with `send_message {teammate} "message"` and read replies with `check_messages`.\n\n' + prompt)
        for command in ('send_message', 'check_messages'):
            shutil.copy2(Path(__file__).with_name('cooperbench_message.py'), assets / command)
            (assets / command).chmod(0o755)
            service['volumes'].append({'type': 'bind', 'source': str(assets / command),
                                       'target': '/usr/local/bin/' + command, 'read_only': True})
        logs = out / 'agent' / name
        logs.mkdir(parents=True, exist_ok=True)
        service['volumes'].extend([
            {'type': 'bind', 'source': str(assets), 'target': '/hr-worker', 'read_only': True},
            {'type': 'bind', 'source': str(logs), 'target': '/out'},
            {'type': 'bind', 'source': str(logs), 'target': '/logs/agent'}])
        service['environment'].update(env)
        service['environment'].update(AGENT_ID=name, REDIS_URL='redis://redis:6379', BASH_ENV='', MSWEA_AGENT_CLASS='')
        service['entrypoint'] = ['bash', '/hr-worker/worker.sh']
    return coordinator
