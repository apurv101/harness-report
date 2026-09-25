import { Pill, type Tone } from '../ui/Pill'
import type { RunSummary, Tests } from '../../lib/types'

/**
 * How the run ended, never a verdict on the reward.  What a reward means is up to each task's verifier (1/0 for
 * all tests passing, a speedup with a floor of 1.0 for AlgoTune, a fraction for a judge), so a scored Harbor run
 * shows the reward as written, in a neutral pill, and what its tests said.
 */
export function EvaluationStatus({ run }: { run: RunSummary }) {
  const [text, tone]: [string, Tone] =
    !run.has_run_json ? ['No result', 'warn']
    : !run.finished ? ['Unfinished', 'warn']
    : run.rc !== 0 || run.errors ? ['Error', 'bad']
    : run.kind !== 'harbor' ? ['Completed', 'plain']
    : run.reward == null ? ['No reward', 'warn']
    : [`reward ${run.reward}`, 'plain']
  return <Pill tone={tone}>{text}</Pill>
}

/** What the verifier reported, in its own terms: the reward as written, the test counts, a non-zero exit. */
export function VerifierSays({ run }: { run: Pick<RunSummary, 'kind' | 'finished' | 'reward' | 'tests' | 'verifier_rc'> }) {
  if (run.kind && run.kind !== 'harbor') return <span className="muted">—</span>
  if (!run.finished) return <span className="muted">…</span>
  return (
    <>
      {run.reward == null ? <Pill tone="warn">no reward</Pill> : <Pill title="as the task's verifier wrote it to reward.txt">reward {run.reward}</Pill>}
      {(run.tests?.total || run.tests?.aborted) ? <> <TestsCell tests={run.tests} /></> : null}
      {run.verifier_rc != null && run.verifier_rc !== 0 && <> <Pill tone="warn" title="the verifier's own exit status">verifier exit {run.verifier_rc}</Pill></>}
    </>
  )
}

export function KindPill({ run }: { run: RunSummary }) {
  return run.kind ? <Pill>{run.kind}</Pill> : <Pill tone="warn">no run.json</Pill>
}

/** How the harness process itself ended, and whether the proxy saw failures on the way. */
export function StatusPill({ run }: { run: RunSummary }) {
  if (!run.has_run_json) return <Pill tone="warn">no run.json</Pill>
  if (!run.finished) return <Pill tone="warn">unfinished</Pill>
  if (run.rc === 0) return (
    <>
      <Pill tone="ok">rc 0</Pill>
      {!!run.errors && <> <Pill tone="bad">{run.errors} proxy err</Pill></>}
    </>
  )
  return <Pill tone="bad">rc {run.rc}</Pill>
}

/** Verifier test counts, e.g. 29 / 31.  Only Harbor runs whose verifier printed pytest -v lines have them. */
export function TestsCell({ tests }: { tests?: Tests | null }) {
  if (tests?.aborted) return <Pill tone="warn" title={tests.aborted}>aborted</Pill>
  if (!tests || !tests.total) return <span className="muted">—</span>
  return (
    <>
      <Pill tone={tests.failed ? 'bad' : 'ok'} title={tests.summary || ''}>{tests.passed} / {tests.total} tests passed</Pill>
      {!!tests.agent_written && (
        <span className="muted small" title="test files the agent itself left in the workdir; pytest ran them too but they are not the task's tests">
          {' '}+{tests.agent_written} own
        </span>
      )}
    </>
  )
}

export function RewardCell({ run }: { run: RunSummary }) {
  if (run.kind !== 'harbor') return <span className="muted">—</span>
  if (run.reward == null) return run.finished ? <Pill tone="warn">none</Pill> : <span className="muted">…</span>
  return <Pill title="as the task's verifier wrote it to reward.txt">{run.reward}</Pill>
}
