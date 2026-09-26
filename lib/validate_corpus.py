#!/usr/bin/env python3
"""Resumable local validation and admission for the ten expansion tasksets.

Run: python3 lib/validate_corpus.py run
Progress: python3 lib/validate_corpus.py status
Every task keeps its original reference solution and grader. Only completed
reference=1 / empty=0 pairs are admitted, and publication is restricted to local DDB.
"""
import argparse
from collections import Counter, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
import tomllib
import uuid

REPO = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get('HARBOR_TASKS', Path.home() / 'Desktop/harbor-tasks'))
CAT = REPO / 'catalog'
WORK = REPO / 'work/validation-batch'
RESULTS = CAT / 'validation-results.jsonl'
SETS = ('ds1000', 'dacode', 'spreadsheetbench-verified', 'scienceagentbench', 'gaia',
        'terminal-bench-2-1', 'devopsgym', 'tau3-bench', 'kumo', 'cooperbench')
COMPOSE = ('docker-compose.yaml', 'docker-compose.yml', 'compose.yaml', 'compose.yml')
STOP = threading.Event()
LOCK = threading.RLock()
BUILD = threading.Lock()
RUNNING = {}
WORKER_STATE = threading.local()
SHARED_IMAGES = {}


class DiskReserveError(RuntimeError):
    pass


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, indent=2) + '\n')
    tmp.replace(path)


def lines(path):
    if not path.exists(): return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def append(path, row):
    with LOCK, path.open('a') as stream:
        stream.write(json.dumps(row) + '\n')
        stream.flush()


def inventory():
    index = json.loads((ROOT / 'TASK-INDEX.json').read_text())
    grouped = defaultdict(deque)
    for relative, paths in index.items():
        ts = Path(relative).name
        if ts not in SETS: continue
        for path in sorted(paths):
            directory = ROOT / path
            if directory.parent != ROOT / relative:
                raise ValueError(f'Nested task path requires explicit integration: {path}')
            grouped[ts].append({'taskset': ts, 'task': directory.name, 'path': path})
    # Round robin ensures all ten sets get attention during the rollout.
    result = []
    while any(grouped.values()):
        for ts in SETS:
            if grouped[ts]: result.append(grouped[ts].popleft())
    return result


def patch_adapters(tasks):
    """Extend only the already-reviewed byte-for-byte template fixes."""
    rules = json.loads((CAT / 'expansion-patches.json').read_text())
    by_set = defaultdict(dict)
    for rule in rules:
        by_set[rule['taskset']][(rule['file'], rule['before_sha256'])] = rule
    evidence = []
    for task in tasks:
        grouped = defaultdict(list)
        for rule in by_set[task['taskset']].values(): grouped[rule['file']].append(rule)
        for leaf, changes in grouped.items():
            path = ROOT / task['path'] / leaf
            if not path.exists(): continue
            before = path.read_bytes(); content = before
            # The tau source pin precedes its import-dependency fix.
            for rule in changes:
                if hashlib.sha256(content).hexdigest() != rule['before_sha256']: continue
                replacement = rule['replace']
                content = content.decode().replace(replacement['old'], replacement['new']).encode()
                if hashlib.sha256(content).hexdigest() != rule['after_sha256']:
                    raise ValueError(f'Unexpected adapter patch result: {path}')
            if content != before:
                path.write_bytes(content)
                evidence.append({'path': str(path.relative_to(ROOT)), 'before_sha256': hashlib.sha256(before).hexdigest(),
                                 'after_sha256': hashlib.sha256(content).hexdigest()})
    if evidence:
        path = CAT / 'validation-adapter-patches.jsonl'
        for row in evidence: append(path, row)
    return len(evidence)


class Resources:
    def __init__(self, capacity):
        self.capacity = capacity
        self.used = 0
        self.condition = threading.Condition()
        self.queue = deque()

    @contextlib.contextmanager
    def acquire(self, amount):
        amount = min(amount, self.capacity)
        ticket = object()
        with self.condition:
            self.queue.append(ticket)
            while self.queue[0] is not ticket or self.used + amount > self.capacity:
                self.condition.wait(1)
                if STOP.is_set():
                    self.queue.remove(ticket); self.condition.notify_all()
                    raise InterruptedError('Validation stopped')
            self.queue.popleft(); self.used += amount; self.condition.notify_all()
        try: yield
        finally:
            with self.condition:
                self.used -= amount; self.condition.notify_all()


def call(args, *, log=None, timeout=60, check=True, env=None):
    if STOP.is_set(): raise InterruptedError('Validation stopped')
    with (Path(log).open('w') if log else contextlib.nullcontext(None)) as output:
        proc = subprocess.Popen([str(a) for a in args], cwd=REPO, stdout=output or subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, env=env, start_new_session=True)
        try:
            deadline = time.monotonic() + timeout
            while True:
                if STOP.is_set(): raise InterruptedError('Validation stopped')
                reserve = getattr(WORKER_STATE, 'min_free_gb', 0)
                if reserve and shutil.disk_usage(REPO).free < reserve * 1024**3:
                    raise DiskReserveError(f'Local disk reserve reached ({reserve} GiB); validation stopped before the disk filled')
                remaining = deadline - time.monotonic()
                if remaining <= 0: raise subprocess.TimeoutExpired(args, timeout)
                try:
                    stdout, _ = proc.communicate(timeout=min(2, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
        except BaseException:
            with contextlib.suppress(ProcessLookupError): os.killpg(proc.pid, signal.SIGTERM)
            try: proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError): os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            raise
    if check and proc.returncode:
        tail = Path(log).read_text(errors='replace')[-2500:] if log else (stdout or '')[-2500:]
        raise RuntimeError(f'{args[0]} exited {proc.returncode}: {tail}')
    return proc.returncode, (stdout or '').strip()


def cleanup(*args):
    subprocess.run(['docker', *map(str, args)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)


def read_reward(folder):
    text = folder / 'reward.txt'
    metrics = folder / 'reward.json'
    if metrics.exists():
        data = json.loads(metrics.read_text())
        value = data.get('reward')
    elif text.exists(): value = float(text.read_text().strip())
    else: return None
    return value if isinstance(value, (float, int)) and not isinstance(value, bool) else None


def reference_passed(result):
    reward = result.get('reward')
    return (type(reward) in (int, float) and reward == 1 and not result.get('error')
            and result.get('solution_rc', 0) in (0, None) and result.get('rc', 0) == 0
            and result.get('backend_rc', 0) == 0 and result.get('verifier_rc', 0) == 0)


def empty_passed(result):
    reward = result.get('reward')
    return (type(reward) in (int, float) and reward == 0 and not result.get('error')
            and result.get('rc', 0) == 0 and result.get('backend_rc', 0) == 0)


def stage(pair, name):
    with LOCK:
        RUNNING[pair] = {'phase': name, 'at': now()}


def single_case(task, cfg, image, out, reference, memory):
    out.mkdir(parents=True)
    _, workdir = call(['docker', 'image', 'inspect', '-f', '{{.Config.WorkingDir}}', image])
    name = 'hr-validation-' + uuid.uuid4().hex[:16]
    try:
        call(['docker', 'run', '-d', '--platform', 'linux/amd64', '--name', name,
              '--label', 'hr.validation=batch', '--memory', f'{memory}m', '--cpus', str(min(cfg.get('environment', {}).get('cpus', 2), 8)),
              '-w', workdir or '/app', '-e', 'TEST_DIR=/tests', image, 'sleep', 'infinity'])
        call(['docker', 'exec', name, 'mkdir', '-p', '/logs/verifier', '/logs/agent', '/tests'])
        solve_rc = None
        if reference:
            call(['docker', 'exec', name, 'mkdir', '-p', '/solution'])
            call(['docker', 'cp', str(task / 'solution') + '/.', name + ':/solution/'], timeout=300)
            solve_rc, _ = call(['docker', 'exec', '-w', workdir or '/app', name, 'bash', '-lc', 'bash /solution/solve.sh'],
                               log=out / 'solution.log', timeout=cfg.get('agent', {}).get('timeout_sec', 1800), check=False)
        call(['docker', 'cp', str(task / 'tests') + '/.', name + ':/tests/'], timeout=300)
        verifier_rc, _ = call(['docker', 'exec', '-w', workdir or '/app', name, 'bash', '-lc', 'bash /tests/test.sh'],
                              log=out / 'verifier.log', timeout=cfg.get('verifier', {}).get('timeout_sec', 1800), check=False)
        call(['docker', 'cp', name + ':/logs/verifier/.', str(out)], timeout=300)
        return {'reward': read_reward(out), 'solution_rc': solve_rc, 'verifier_rc': verifier_rc}
    finally: cleanup('rm', '-f', name)


def compose_case(task, image, out, reference):
    out.mkdir(parents=True)
    net = 'hr-validation-' + uuid.uuid4().hex[:16]
    _, wd = call(['docker', 'image', 'inspect', '-f', '{{.Config.WorkingDir}}', image])
    call(['docker', 'network', 'create', '--label', 'hr.validation=batch', net])
    command = [sys.executable, REPO / 'lib/harbor_python.py', 'run', '--task', task, '--image', image,
               '--out', out, '--work', out / 'work', '--workdir', wd or '/app', '--platform', 'linux/amd64',
               '--network', net, '--verify-network', net, '--egress', 'open']
    if reference: command += ['--oracle']
    else:
        write_json(out / 'recipe.json', {'env': []})
        (out / 'nop.sh').write_text('#!/bin/bash\nexit 0\n')
        command += ['--recipe', out / 'recipe.json', '--wrapper', out / 'nop.sh']
    try:
        cfg = tomllib.loads((task / 'task.toml').read_text())
        timeout = sum(cfg.get(phase, {}).get('timeout_sec', 1800) for phase in ('agent', 'verifier')) + cfg.get('environment', {}).get('build_timeout_sec', 1800) + 180
        rc, _ = call(command, log=out / 'console.log', timeout=timeout, check=False)
        result = json.loads((out / 'harbor-result.json').read_text())
        value = {'reward': result['reward'], 'rc': result['rc'], 'backend_rc': rc, 'error': result.get('error')}
        # Oracle failures can still produce a reward. Inspect its authoritative exit code.
        if reference:
            exit_path = out / 'agent/exit-code.txt'
            value['solution_rc'] = int(exit_path.read_text().strip()) if exit_path.exists() else 0
            agent_result = result.get('trial', {}).get('agent_result') or {}
            value['agent_result'] = agent_result
        return value
    finally: cleanup('network', 'rm', net)


def preflight(task, cfg, available_memory):
    if not (task / 'solution/solve.sh').is_file(): return 'No reference solution is provided'
    if not (task / 'tests/test.sh').is_file(): return 'No supported verifier entrypoint is provided'
    environment = cfg.get('environment', {})
    if environment.get('gpus', 0): return 'Task requires a GPU; the local Docker runtime has no GPU'
    if environment.get('memory_mb', 0) > available_memory * 1.15:
        return f'Task requests {environment["memory_mb"]} MiB; local Docker has {available_memory} MiB'
    if (task / 'tests/visual_judge.py').exists():
        return 'Visual grading requires an external judge model; no judge service is configured for this local batch'
    if not any((task / 'environment' / n).exists() for n in ('Dockerfile', *COMPOSE)) and not environment.get('docker_image'):
        return 'Task has no Dockerfile, Compose definition, or container image'
    return None


def validate(row, resources, memory, min_free_gb):
    pair = row['taskset'] + '/' + row['task']
    task = ROOT / row['path']
    cfg = tomllib.loads((task / 'task.toml').read_text())
    record = {**row, 'at': now(), 'platform': 'linux/amd64'}
    reason = preflight(task, cfg, memory)
    if reason: return {**record, 'status': 'blocked', 'reason': reason}
    requested = int(min(cfg.get('environment', {}).get('memory_mb', 2048), memory - 3072))
    out = WORK / row['taskset'] / row['task'] / uuid.uuid4().hex[:8]
    out.mkdir(parents=True)
    record['logs'] = str(out.relative_to(REPO))
    tag = 'hr-validation/' + row['taskset'] + ':' + uuid.uuid4().hex[:12]
    image = tag
    started = time.monotonic()
    compose = any((task / 'environment' / n).is_file() for n in COMPOSE)
    try:
        WORKER_STATE.min_free_gb = min_free_gb
        with resources.acquire(requested):
            stage(pair, 'building')
            with BUILD:
                if shutil.disk_usage(REPO).free < min_free_gb * 1024**3:
                    return {**record, 'status': 'blocked', 'reason': f'Local disk reserve reached ({min_free_gb} GiB); task was not run'}
                env = cfg.get('environment', {})
                timeout = env.get('build_timeout_sec', 1800)
                if compose:
                    call([sys.executable, REPO / 'lib/harbor_python.py', 'image', '--task', task, '--work', out / 'build',
                          '--image', image, '--platform', 'linux/amd64'], log=out / 'build.log', timeout=timeout + 120)
                elif (task / 'environment/Dockerfile').is_file():
                    # DS-1000 has a byte-identical environment with no task assets in its
                    # image. Its tests and solution are copied into fresh containers.
                    dockerfile = (task / 'environment/Dockerfile').read_bytes()
                    template = ROOT / 'datasets/ds1000/0/environment/Dockerfile'
                    shared = row['taskset'] == 'ds1000' and dockerfile == template.read_bytes()
                    key = hashlib.sha256(dockerfile).hexdigest() if shared else None
                    if shared and key in SHARED_IMAGES:
                        image = SHARED_IMAGES[key]
                        (out / 'build.log').write_text('Reused identical DS-1000 environment: ' + image + '\n')
                    else:
                        if shared: image = 'hr-validation/shared:' + key[:20]
                        call(['docker', 'build', '--platform', 'linux/amd64', '-t', image, task / 'environment'], log=out / 'build.log', timeout=timeout)
                        if shared: SHARED_IMAGES[key] = image
                else:
                    image = env['docker_image']
                    rc, _ = call(['docker', 'image', 'inspect', image], check=False)
                    if rc: call(['docker', 'pull', '--platform', 'linux/amd64', image], log=out / 'build.log', timeout=timeout)
            case = lambda ref: compose_case(task, image, out / ('reference' if ref else 'empty'), ref) if compose else single_case(task, cfg, image, out / ('reference' if ref else 'empty'), ref, requested)
            stage(pair, 'reference')
            record['reference'] = case(True)
            ref = record['reference']
            if not reference_passed(ref):
                record.update(status='failed', reason='Reference solution did not complete successfully with reward 1')
            else:
                stage(pair, 'empty-submission')
                record['empty'] = case(False)
                empty = record['empty']
                passed = empty_passed(empty)
                record.update(status='passed' if passed else 'failed', reason=None if passed else 'Empty submission did not produce reward 0 without an infrastructure error')
    except DiskReserveError as error:
        record.update(status='blocked', reason=str(error))
    except InterruptedError:
        record.update(status='interrupted', reason='Validation stopped; task will be retried on resume')
    except subprocess.TimeoutExpired as error:
        record.update(status='failed', reason=f'Execution exceeded the configured {error.timeout}s timeout')
    except Exception as error:
        record.update(status='failed', reason=str(error)[-3000:])
    finally:
        if image == tag: cleanup('image', 'rm', image)
        # Only images built by this trial are removed; pre-existing images/caches are preserved.
        for candidate in out.glob('*/work/task/environment/docker-compose.yaml'):
            with contextlib.suppress(Exception):
                config = json.loads(candidate.read_text())
                for service in config.get('services', {}).values():
                    if service.get('image', '').startswith('hr-sidecar/hr-hb-'): cleanup('image', 'rm', service['image'])
        with LOCK: RUNNING.pop(pair, None)
        WORKER_STATE.min_free_gb = 0
    record.update(seconds=round(time.monotonic() - started), completed_at=now())
    write_json(out / 'validation.json', record)
    return record


def publish(records):
    """Publish only fully validated pairs; preserve existing candidates and results."""
    if not records: return
    import ddb, store, tasks
    for row in records:
        if row.get('status') != 'passed': raise ValueError('Only passed validations can be published')
        if not row.get('imported_validation') and not (reference_passed(row.get('reference', {})) and empty_passed(row.get('empty', {}))):
            raise ValueError('Missing successful reference and empty-submission evidence')
    if not ddb.local() or ddb.endpoint() != 'http://127.0.0.1:8001':
        raise RuntimeError('Full-corpus validation is authorized for the local catalog only')
    latest = {(r['taskset'], r['task']): r for r in lines(CAT / 'oracle.jsonl')}
    for row in records:
        oracle = {'taskset': row['taskset'], 'task': row['task'], 'reward': 1, 'seconds': row.get('seconds', 0),
                  'platform': 'linux/amd64', 'at': row.get('completed_at', row['at']), 'validation': row['logs']}
        append(CAT / 'oracle.jsonl', oracle); latest[(row['taskset'], row['task'])] = oracle
    path = CAT / 'runnable.json'
    with (WORK / 'catalog.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = json.loads(path.read_text()); existing = {(r['taskset'], r['task']) for r in data['tasks']}
        for row in records:
            key = (row['taskset'], row['task'])
            if key not in existing:
                data['tasks'].append({'taskset': key[0], 'task': key[1]}); existing.add(key)
        write_json(path, data)
    live = {key for key in existing if latest.get(key, {}).get('reward') == 1}
    items = []
    for row in records:
        ts, name = row['taskset'], row['task']
        old = ddb.get(store.taskset_pk(ts), 'TASK#' + name) or {}
        card = tasks.task_card(str((ROOT / row['path']).parent), name, ts, live, latest)
        for key in ('results', 'runs'):
            if key in old: card[key] = old[key]
        items.extend([{**card, 'pk': store.taskset_pk(ts), 'sk': 'TASK#' + name},
                      {**card, 'pk': store.RUNNABLE, 'sk': store.task_key(ts, name)}])
    for ts in {r['taskset'] for r in records}:
        metadata = ddb.get(store.taskset_pk(ts), 'META')
        if not metadata: raise RuntimeError('Taskset card must exist before batch publication: ' + ts)
        metadata['n_runnable'] = sum(1 for key in live if key[0] == ts)
        items.extend([metadata, {**metadata, 'pk': store.TASKSETLIST, 'sk': store.taskset_pk(ts)}])
    ddb.batch_put(items)


def summary(tasks, latest, state):
    by_set = {ts: Counter(total=sum(t['taskset'] == ts for t in tasks)) for ts in SETS}
    keys = {(t['taskset'], t['task']) for t in tasks}
    for key, record in latest.items():
        if key in keys: by_set[record['taskset']][record['status']] += 1
    for values in by_set.values(): values['pending'] = values['total'] - sum(v for k, v in values.items() if k != 'total')
    report = {'updated_at': now(), 'state': state, 'total': len(tasks), 'completed': sum(key in keys for key in latest),
              'by_taskset': by_set, 'running': dict(RUNNING)}
    write_json(WORK / 'status.json', report)
    total = Counter()
    for counts in by_set.values(): total.update(counts)
    text = ['# Full taskset validation', '', f'Updated: {report["updated_at"]}. Batch state: **{state}**.', '',
            'Validation and publication are local only. Passing means the reference solution scored 1 and a fresh empty submission scored 0; failed and blocked tasks remain disabled.', '',
            '| Taskset | Total | Passed | Failed | Blocked | Pending |', '| --- | ---: | ---: | ---: | ---: | ---: |']
    for ts, counts in by_set.items():
        text.append('| ' + ts + ' | ' + ' | '.join(str(counts.get(k, 0)) for k in ('total', 'passed', 'failed', 'blocked', 'pending')) + ' |')
    text += ['', f'**{total["passed"]} validated tasks** across these tasksets; {total["pending"]} pending. Passing tasks are published automatically; any publication failures are recorded separately.', '',
             'Detailed evidence: [validation-results.jsonl](catalog/validation-results.jsonl).',
             'Run `python3 lib/validate_corpus.py status` for live stages and `python3 lib/validate_corpus.py run` to resume after interruption.',
             'Blocked tasks can be retried with `--retry` once their prerequisites are available.']
    if RUNNING:
        text += ['', 'Currently working on:']
        text += [f'- {pair}: {detail["phase"]}' for pair, detail in RUNNING.items()]
    (REPO / 'VALIDATION-PROGRESS.md').write_text('\n'.join(text) + '\n')
    return report


def run(args):
    WORK.mkdir(parents=True, exist_ok=True)
    guard = (WORK / 'controller.lock').open('w')
    fcntl.flock(guard, fcntl.LOCK_EX | (0 if args.wait else fcntl.LOCK_NB))
    os.environ.update(HR_DDB='local', HR_DDB_ENDPOINT='http://127.0.0.1:8001')
    import ddb
    if ddb.exists() != 'ACTIVE': raise RuntimeError('Start local DynamoDB before validation')
    _, raw = call(['docker', 'info', '--format', '{{.MemTotal}}'])
    memory = int(raw) // (1024 * 1024)
    tasks = inventory()
    if args.tasksets: tasks = [t for t in tasks if t['taskset'] in args.tasksets.split(',')]
    print(f'{len(tasks)} tasks; {memory} MiB Docker memory; {args.workers} workers', flush=True)
    print(f'Applied reviewed adapter fixes to {patch_adapters(tasks)} additional files', flush=True)
    latest = {(r['taskset'], r['task']): r for r in lines(RESULTS)}
    for old in json.loads((CAT / 'expansion.json').read_text())['tasks']:
        key = old['taskset'], old['task']
        if key not in latest:
            row = {**next(t for t in inventory() if (t['taskset'], t['task']) == key), 'status': 'passed',
                   'at': now(), 'imported_validation': True, 'logs': old['empty_submission']['logs']}
            append(RESULTS, row); latest[key] = row
    pending = [t for t in tasks if (t['taskset'], t['task']) not in latest or latest[(t['taskset'], t['task'])]['status'] == 'interrupted'
               or args.retry and latest[(t['taskset'], t['task'])]['status'] in ('failed', 'blocked')]
    if args.max_tasks: pending = pending[:args.max_tasks]
    # Reconcile completed passes after any interruption between validation and publication.
    import store
    candidate_keys = {(r['taskset'], r['task']) for r in store.runnable_list()}
    unpublished = [r for key, r in latest.items() if r['status'] == 'passed' and key not in candidate_keys]
    publish(unpublished)
    resources = Resources(memory - 3072)
    def refresh():
        while not STOP.wait(10):
            with LOCK: summary(tasks, latest, 'running')
    thread = threading.Thread(target=refresh, daemon=True); thread.start()
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(validate, row, resources, memory, args.min_free_gb): row for row in pending}
            for future in as_completed(futures):
                try:
                    row = future.result()
                except Exception as error:
                    row = {**futures[future], 'at': now(), 'status': 'failed', 'reason': str(error)[-3000:]}
                append(RESULTS, row)
                with LOCK: latest[(row['taskset'], row['task'])] = row
                if row['status'] == 'passed':
                    try: publish([row])
                    except Exception as error:
                        append(WORK / 'publication-errors.jsonl', {'at': now(), 'taskset': row['taskset'], 'task': row['task'], 'error': str(error)})
                        print('Publication deferred; validation evidence is saved: ' + str(error), flush=True)
                print(json.dumps({k: row.get(k) for k in ('taskset', 'task', 'status', 'seconds', 'reason')}), flush=True)
                if STOP.is_set():
                    for f in futures: f.cancel()
                    break
    finally:
        STOP.set(); thread.join(timeout=2)
        for image in SHARED_IMAGES.values(): cleanup('image', 'rm', image)
        with LOCK: report = summary(tasks, latest, 'complete' if all((t['taskset'], t['task']) in latest and latest[(t['taskset'], t['task'])]['status'] != 'interrupted' for t in tasks) else 'incomplete')
        print(json.dumps(report), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['run', 'status'])
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--wait', action='store_true', help='wait for an existing validation controller to finish')
    parser.add_argument('--max-tasks', type=int)
    parser.add_argument('--tasksets')
    parser.add_argument('--retry', action='store_true')
    parser.add_argument('--min-free-gb', type=int, default=10)
    args = parser.parse_args()
    if args.command == 'status':
        print((WORK / 'status.json').read_text() if (WORK / 'status.json').exists() else 'No batch started')
    else:
        signal.signal(signal.SIGTERM, lambda *_: STOP.set())
        signal.signal(signal.SIGINT, lambda *_: STOP.set())
        run(args)
