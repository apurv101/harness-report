import { Pill } from '../ui/Pill'
import { VerifierSays } from '../runs/RunStatus'
import type { Outcomes, RunRow } from '../../lib/types'

/**
 * One run's result as its verifier reported it: the reward as written (neutral — what it means is the task's
 * business) and what the tests said.  Only the states that are not about scoring get a tone.
 */
export function OutcomePill({ run }: { run: Pick<RunRow, 'outcome' | 'reward' | 'tests' | 'verifier_rc'> }) {
  if (run.outcome === 'running') return <Pill tone="warn">Running</Pill>
  if (run.outcome === 'error') return <Pill tone="warn">No reward</Pill>
  return <VerifierSays run={{ kind: 'harbor', finished: 'yes', reward: run.reward, tests: run.tests, verifier_rc: run.verifier_rc }} />
}

/** Several runs of one harness on one task, folded: the latest reward and the best, and what the last tests said. */
export function OutcomesCell({ o }: { o: Outcomes }) {
  if (o.last_outcome === 'running') return <Pill tone="warn">Running</Pill>
  const tests = o.last_tests
  return (
    <>
      {o.last_reward == null ? <Pill tone="warn">no reward</Pill> : <Pill title="the latest run's reward, as its verifier wrote it">reward {o.last_reward}</Pill>}
      {o.runs > 1 && o.best_reward != null && String(o.best_reward) !== String(o.last_reward) &&
        <span className="muted small"> best {o.best_reward}</span>}
      {tests?.summary && <span className="muted small"> · {tests.summary}</span>}
      <span className="muted small"> · {o.runs} run{o.runs === 1 ? '' : 's'}</span>
    </>
  )
}

/** A page's machine-readable twins, for anyone (or anything) that would rather read Markdown or JSON. */
export function Twins({ path }: { path: string }) {
  return (
    <p className="muted small twins">
      For agents: <a href={`${path}.md`}>{path}.md</a> · <a href={`${path}.json`}>.json</a> · <a href="/llms.txt">llms.txt</a>
    </p>
  )
}
