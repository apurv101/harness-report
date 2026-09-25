import { useId, useState } from 'react'
import type { RunBundle, TestCase } from '../../../lib/types'
import { Pill } from '../../ui/Pill'
import { LogBlock } from './LogBlock'

const failed = (test: TestCase) => test.result === 'FAILED' || test.result === 'ERROR'
const keyOf = (test: TestCase) => test.id || `${test.file}::${test.name}`

/** All recorded tests, with the output belonging to each test and the original suite logs. */
export function TestsTab({ bundle }: { bundle: RunBundle }) {
  const tests = bundle.verifier?.tests
  const cases = tests?.cases || []
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('all')
  const [expanded, setExpanded] = useState(() => new Set(cases.filter(failed).map(keyOf)))
  const panelId = useId()
  const visible = cases.filter(test =>
    `${test.name} ${test.file}`.toLowerCase().includes(query.trim().toLowerCase()) &&
    (filter === 'all' || (filter === 'failed' ? failed(test) : filter === 'passed' ? test.result === 'PASSED' :
      !failed(test) && test.result !== 'PASSED')))
  const toggle = (key: string) => setExpanded(previous => {
    const next = new Set(previous)
    if (next.has(key)) next.delete(key); else next.add(key)
    return next
  })
  const live = !bundle.run_json.finished
  const cut = (name: string) => bundle.truncated.includes(name)

  return (
    <div className="tests-section">
      <h2>All tests {cases.length > 0 && <span className="muted">· {cases.length}</span>}</h2>
      <p className="small muted">Open a test to see its recorded output, failure traceback, and source. Results update while the run is in progress.</p>
      {!!tests?.total && <p className="small">
        <strong>{tests.passed} passed · {tests.failed} failed · {tests.total} counted</strong>
        {!!tests.agent_written && <span className="muted"> · {tests.agent_written} agent-written, not counted</span>}
      </p>}
      {tests?.aborted && <p className="tests-alert" role="status">Test execution stopped: {tests.aborted}. See the complete test output below.</p>}

      {cases.length > 0 ? <>
        <div className="tests-toolbar">
          <label>Search tests<input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Test name or file" /></label>
          <label>Result<select value={filter} onChange={event => setFilter(event.target.value)}>
            <option value="all">All results</option><option value="failed">Failed / errors</option>
            <option value="passed">Passed</option><option value="other">Skipped / other</option>
          </select></label>
          <button className="ui-btn small" onClick={() => setExpanded(new Set(visible.map(keyOf)))}>Expand all</button>
          <button className="ui-btn small" onClick={() => setExpanded(new Set())}>Collapse all</button>
        </div>
        <p className="small muted" role="status">Showing {visible.length} of {cases.length} recorded tests</p>
        <div className="test-cases">
          {visible.map((test, index) => {
            const key = keyOf(test)
            const open = expanded.has(key)
            const id = `${panelId}-${index}`
            return <article className="test-case" key={key}>
              <button className="test-case-toggle" aria-expanded={open} aria-controls={id} onClick={() => toggle(key)}>
                <span className="test-chevron" aria-hidden="true">{open ? '−' : '+'}</span>
                <span className="test-case-name"><strong>{test.name}</strong><span>{test.file}{!test.own && ' · Agent-written, not counted'}</span></span>
                <Pill tone={failed(test) ? 'bad' : test.result === 'PASSED' ? 'ok' : 'warn'}>{test.result}</Pill>
              </button>
              <div id={id} className="test-case-body" hidden={!open}>
                <h3>{failed(test) ? 'Failure log' : 'Recorded output'}</h3>
                {test.detail ? <pre>{test.detail}</pre> : <p className="small muted">
                  {failed(test) ? 'The verifier did not record a separate traceback for this test. Check the complete test output below.' :
                    'No separate output was recorded for this test. Its result is shown above; shared output is available below.'}
                </p>}
                {test.source && <details><summary>Test source</summary><pre>{test.source}</pre></details>}
              </div>
            </article>
          })}
        </div>
        {visible.length === 0 && <p className="empty">No tests match these filters.</p>}
      </> : <p className="empty" role="status">
        {live ? 'Individual test results will appear when the verifier reports them.' : tests?.aborted ?
          'No individual results were recorded before the test suite stopped.' :
          'No individual test results are available for this run. Check the complete test output below for the result and any errors.'}
      </p>}

      <h2>Complete test output</h2>
      <p className="small muted">The verifier’s original output includes shared setup, collection errors, and any output that could not be assigned to one test.</p>
      <LogBlock title="verifier/stdout.log" text={bundle.verifier?.['stdout.log']} run={bundle.run} cut={cut('verifier/stdout.log')} />
      <LogBlock title="verifier/stderr.log" text={bundle.verifier?.['stderr.log']} run={bundle.run} cut={cut('verifier/stderr.log')} />
    </div>
  )
}
