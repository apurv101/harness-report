import { fmt, shortModel } from '../../lib/format'
import type { Call, RunBundle } from '../../lib/types'
import { Fact, Facts } from '../ui/Fact'

/** Token and latency totals the proxy recorded, added up over the run's calls. */
export function callTotals(calls: Call[]) {
  return {
    in: calls.reduce((a, c) => a + (c.usage?.input_tokens || 0), 0),
    out: calls.reduce((a, c) => a + (c.usage?.output_tokens || 0), 0),
    err: calls.filter(c => c.error).length,
    ms: calls.reduce((a, c) => a + (c.latency_ms || 0), 0),
  }
}

/** The half of run.json written before anything ran: what harness, what task, what model. */
export function OriginFacts({ bundle }: { bundle: RunBundle }) {
  const run = bundle.run_json
  const harness = run.harness || {}
  const task = run.task || {}
  const harbor = run.kind === 'harbor'
  return (
    <>
      <h2>
        <span className="help" title="The half of run.json written before anything ran: what harness, what task, what model. A run that died mid-way still has this.">
          Origin
        </span>
      </h2>
      <Facts>
        <Fact name="kind" value={run.kind} />
        <Fact name="harness" value={harness.name} />
        <Fact name="api" value={harness.api_style} />
        {harbor
          ? <><Fact name="taskset" value={task.taskset} /><Fact name="task" value={task.name} /></>
          : <Fact name="task" value="prompt (below)" />}
        <Fact name="model" value={shortModel(run.model)} />
        <Fact name="workdir" value={run.workdir} />
        <Fact name="started" value={run.started} />
      </Facts>
      {harbor && task.taskset_dir && (
        <p className="muted small mono">task folder: {task.taskset_dir}/{task.name}</p>
      )}
    </>
  )
}

/** The half merged in when the run ended: exit code, timing, reward, and the proxy's totals. */
export function ResultFacts({ bundle }: { bundle: RunBundle }) {
  const run = bundle.run_json
  const calls = bundle.calls
  const harbor = run.kind === 'harbor'
  const total = callTotals(calls)
  return (
    <>
      <h2>
        <span className="help" title="The half of run.json merged in when the run ended: exit code, timing, reward, and the call and token totals from the proxy.">
          Result
        </span>
      </h2>
      <Facts>
        <Fact name="finished" value={run.finished || 'not yet'} />
        <Fact name="exit code" value={run.rc} />
        <Fact name="wall time" value={run.seconds != null ? `${run.seconds} s` : null} />
        {harbor && <>
          <Fact name="reward" value={run.reward} />
          <Fact name="verifier rc" value={run.verifier_rc} />
          {!!run.tests?.total && (
            <Fact name="tests" value={`${run.tests.passed} passed, ${run.tests.failed} failed, ${run.tests.total} total`} />
          )}
        </>}
        <Fact name="model calls" value={`${calls.length}${bundle.calls_unparsed ? ` (+${bundle.calls_unparsed} unparsed)` : ''}`} />
        <Fact name="tokens in" value={fmt(total.in)} />
        <Fact name="tokens out" value={fmt(total.out)} />
        <Fact name="model time" value={`${(total.ms / 1000).toFixed(1)} s`} />
        <Fact name="proxy errors" value={total.err} />
        <Fact name="model requested" value={calls[0]?.model_requested} />
        <Fact name="first call" value={calls[0]?.ts} />
      </Facts>
    </>
  )
}
