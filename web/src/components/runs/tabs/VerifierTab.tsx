import { Fragment, useState } from 'react'
import type { RunBundle, TestCase } from '../../../lib/types'
import { Fact, Facts } from '../../ui/Fact'
import { Pill } from '../../ui/Pill'
import { LogBlock } from './LogBlock'

/** Harbor runs only: what tests/test.sh printed, and the reward it wrote. */
export function VerifierTab({ bundle }: { bundle: RunBundle }) {
  const verifier = bundle.verifier
  const run = bundle.run_json
  if (!verifier) return <div className="empty">no verifier/ folder: the run did not reach the verify stage.</div>
  const tests = verifier.tests

  return (
    <>
      <Facts>
        <Fact name="reward" value={(verifier['reward.txt'] || '').trim() || null} />
        <Fact name="verifier rc" value={run.verifier_rc} />
        <Fact name="taskset" value={run.task?.taskset} />
        <Fact name="task" value={run.task?.name} />
        {!!tests?.total && <Fact name="tests" value={`${tests.passed} passed, ${tests.failed} failed, ${tests.total} total`} />}
        {tests?.aborted && <Fact name="tests" value={`aborted: ${tests.aborted}`} />}
      </Facts>

      {tests?.aborted && (
        <p className="small muted">
          Test execution stopped: <span className="mono">{tests.aborted}</span>.
          {tests.total ? ' Results below include the tests that were reported before it stopped.' : ' No individual test results were recorded.'}
        </p>
      )}

      {!!tests?.total && (
        <p className="small muted">
          The task's own test suite, run by <code>tests/test.sh</code> in the sandbox after the agent finished.
          The reward is whatever this task's verifier wrote; what it means depends on the task, so read it next to these results.
          {tests.summary && <> pytest: <span className="mono">{tests.summary}</span></>}
          {!!tests.agent_written && ` pytest also collected ${tests.agent_written} test${tests.agent_written === 1 ? '' : 's'} from files the agent wrote itself; they are not counted here.`}
        </p>
      )}

      {!!tests?.cases?.length && <TestCases cases={tests.cases} />}

      <LogBlock title="verifier/stdout.log" text={verifier['stdout.log']} run={bundle.run} cut={bundle.truncated.includes('verifier/stdout.log')} />
      <LogBlock title="verifier/stderr.log" text={verifier['stderr.log']} run={bundle.run} cut={bundle.truncated.includes('verifier/stderr.log')} />
    </>
  )
}

/** Every test in pytest order; open one for its source and, when it failed, the traceback. */
function TestCases({ cases }: { cases: TestCase[] }) {
  const [open, setOpen] = useState<number | null>(null)
  const tone = (result: string) => (/PASS/.test(result) ? 'ok' : /FAIL|ERROR/.test(result) ? 'bad' : 'warn')

  return (
    <>
      <h2>
        tests <span className="muted" style={{ textTransform: 'none', letterSpacing: 0 }}>
          {cases.length}, click one for its source and, if it failed, the traceback
        </span>
      </h2>
      <table>
        <thead><tr><th>#</th><th>result</th><th>test</th><th>file</th></tr></thead>
        <tbody>
          {cases.map((test, i) => (
            <Fragment key={i}>
              <tr className="row" onClick={() => setOpen(current => (current === i ? null : i))}>
                <td className="num">{i + 1}</td>
                <td><Pill tone={tone(test.result)}>{test.result}</Pill></td>
                <td className="mono small">{test.name}</td>
                <td className="mono small">
                  {test.file}{!test.own && <span className="muted"> (agent-written, not counted)</span>}
                </td>
              </tr>
              {open === i && (
                <tr className="detail">
                  <td />
                  <td colSpan={3}>
                    {test.source
                      ? <><div className="muted small">source</div><pre>{test.source}</pre></>
                      : <div className="muted small">source not available (task folder not readable from here)</div>}
                    {test.detail && <><div className="muted small">failure</div><pre>{test.detail}</pre></>}
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </>
  )
}
