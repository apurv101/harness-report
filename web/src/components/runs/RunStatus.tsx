import { Pill, type Tone } from '../ui/Pill'
import type { RunSummary, Tests } from '../../lib/types'

/**
 * The one-word verdict in the index.  A Harbor run is judged by its reward; a prompt run has
 * nothing to judge it, so finishing cleanly is all it can claim.
 */
export function EvaluationStatus({ run }: { run: RunSummary }) {
  const [text, tone]: [string, Tone] =
    !run.has_run_json ? ['No result', 'warn']
    : !run.finished ? ['Unfinished', 'warn']
    : run.rc !== 0 || run.errors ? ['Error', 'bad']
    : run.kind !== 'harbor' ? ['Completed', 'ok']
    : run.reward == null ? ['No result', 'warn']
    : Number(run.reward) === 1 ? ['Passed', 'ok']
    : Number(run.reward) > 0 ? ['Partial', 'warn']
    : ['Failed', 'bad']
  return <Pill tone={tone}>{text}</Pill>
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
      <Pill tone={tests.failed ? 'bad' : 'ok'} title={tests.summary || ''}>{tests.passed} / {tests.total}</Pill>
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
  return <Pill tone={Number(run.reward) > 0 ? 'ok' : 'bad'}>{run.reward}</Pill>
}
