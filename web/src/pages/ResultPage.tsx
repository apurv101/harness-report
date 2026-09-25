import { Link, Navigate, useNavigate } from 'react-router-dom'
import { FlowLayout } from '../components/onboarding/FlowLayout'
import { SelectedRepo } from '../components/onboarding/SelectedRepo'
import { Icon } from '../components/ui/Icon'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { useEvaluation } from '../hooks/useEvaluation'
import { evalConsoleURL } from '../lib/api'
import { NextTests } from '../components/entities/NextTests'
import { inProgress, progress, taskTitle } from '../lib/evaluation'
import { FIZZBUZZ_OUTPUT } from '../lib/preview'
import { usePreview } from '../state/PreviewContext'

const CHECKS = ['Repository fetched', 'Model connection verified', 'Environment prepared', 'Output matches expected result']

const FACTS = [['TASK RESULT', 'Passed'], ['MODEL CALLS', '6'], ['RUN TIME', '21s']] as const

/** Step 4: the real run's outcome when there is one; otherwise the preview's example report. */
export function ResultPage() {
  const { evalId } = usePreview()
  return evalId ? <LiveResult id={evalId} /> : <ExampleResult />
}

function LiveResult({ id }: { id: string }) {
  useDocumentTitle('First task result · Harness Report')
  const { repo, setEval } = usePreview()
  const navigate = useNavigate()
  const { state, events, error } = useEvaluation(id)
  if (error && !state) return <FlowLayout step={4}><p className="flow-helper">Could not load the run: {error}</p></FlowLayout>
  if (!state) return <FlowLayout step={4}><p className="flow-helper">Loading the result…</p></FlowLayout>
  if (inProgress(state.eval.status)) return <Navigate to={`/check?repo=${encodeURIComponent(state.eval.repo)}&eval=${encodeURIComponent(id)}`} replace />

  const ev = state.eval; const r = state.result; const t = r?.tests
  const title = taskTitle(ev.task)
  const passed = ev.status === 'done' && r?.reward === 1
  const { details, error: stopped } = progress(events, state.live, state)
  const heading = ev.status === 'cancelled' ? 'Run cancelled.'
    : ev.status === 'failed' ? 'The run stopped before the tests.'
    : passed ? 'First task passed.' : 'First task finished.'
  const sub = ev.status === 'done' && t?.total ? `${title} · ${t.passed} of ${t.total} tests passed`
    : stopped ? `${title} · ${stopped}` : `${title} · ${ev.taskset}`
  const facts: [string, string][] = [
    ['TASK RESULT', ev.status !== 'done' ? '—' : passed ? 'Passed' : 'Failed'],
    ['TESTS', t?.total ? `${t.passed}/${t.total}` : '—'],
    ['MODEL CALLS', String(r?.calls ?? state.live.calls)],
    ['AGENT TIME', r?.seconds != null ? `${r.seconds}s` : '—'],
  ]
  const log = events.filter(e => e.type === 'stage' || e.type === 'error')
    .map(e => e.type === 'error' ? `[error] ${e.msg}` : `[${String(e.t ?? 0).padStart(4)}s] ${e.stage}: ${(e.msg || '').split('\n')[0]}`).join('\n')

  return (
    <FlowLayout step={4}>
      <div className="success-heading">
        <span className="success-symbol"><Icon name={passed ? 'check' : 'terminal'} /></span>
        <div><h1 tabIndex={-1}>{heading}</h1><p>{sub}</p></div>
      </div>
      <SelectedRepo repo={ev.repo || repo!} />
      <div className="flow-card">
        <div className="result-banner">
          <strong>{title}</strong>
          <span className="pass-label">{passed ? <><Icon name="check" /> Passed</> : ev.status === 'done' ? 'Not passed' : ev.status}</span>
        </div>
        <div className="result-details">
          <dl className="result-facts" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
            {facts.map(([term, value]) => <div key={term}><dt>{term}</dt><dd>{value}</dd></div>)}
          </dl>
          <div className="result-checks">
            {details.filter(Boolean).map(d => <span key={d}><Icon name="check" /> {d!.split('\n')[0]}</span>)}
          </div>
          {t && t.failed > 0 && (
            <div className="expected-output"><span>FAILED TESTS</span><code>{t.failed_names.slice(0, 8).join('\n')}{t.failed_names.length > 8 ? `\n… ${t.failed_names.length - 8} more` : ''}</code></div>
          )}
          <details>
            <summary>View the run log</summary>
            <pre>{log || 'No stages were recorded.'}</pre>
          </details>
        </div>
      </div>
      <div className="result-links">
        {r && <Link className="text-link" to={`/runs/${encodeURIComponent(ev.run)}`}>Open the full run</Link>}
        <a className="text-link" href={evalConsoleURL(id)} target="_blank" rel="noopener">Console log</a>
        <button onClick={() => { setEval(null); navigate('/check') }}>Run again</button>
        {ev.harness && <Link to={`/harnesses/${encodeURIComponent(ev.harness)}`} className="text-link">Harness page</Link>}
        <Link to="/import" className="text-link">Choose another harness</Link>
      </div>
      {ev.status === 'done' && (
        <NextTests harness={ev.harness || ev.repo.replace('/', '-').toLowerCase()} repo={ev.repo} afterRun={ev.run}
                   onStarted={id => { setEval(id); navigate(`/check?repo=${encodeURIComponent(ev.repo)}&eval=${encodeURIComponent(id)}`) }} />
      )}
    </FlowLayout>
  )
}

/** The example report the preview ends on.  Every number here is illustrative. */
function ExampleResult() {
  useDocumentTitle('First task complete · Harness Report')
  const { repo, setResult } = usePreview()
  const navigate = useNavigate()

  return (
    <FlowLayout step={4}>
      <div className="success-heading">
        <span className="success-symbol"><Icon name="check" /></span>
        <div><h1 tabIndex={-1}>First task complete.</h1><p>FizzBuzz · Example result</p></div>
      </div>
      <SelectedRepo repo={repo!} />
      <div className="flow-card">
        <div className="result-banner">
          <strong>FizzBuzz</strong>
          <span className="pass-label"><Icon name="check" /> Example pass</span>
        </div>
        <div className="result-details">
          <dl className="result-facts">
            {FACTS.map(([term, value]) => <div key={term}><dt>{term}</dt><dd>{value}</dd></div>)}
          </dl>
          <p className="flow-bottom-note" style={{ justifyContent: 'flex-start', marginTop: 0 }}>Illustrative results · Preview only</p>
          <div className="result-checks">
            {CHECKS.map(c => <span key={c}><Icon name="check" /> {c}</span>)}
          </div>
          <div className="expected-output"><span>EXAMPLE OUTPUT · FIZZBUZZ 1–15</span><code>{FIZZBUZZ_OUTPUT}</code></div>
          <details>
            <summary>View example check log</summary>
            <pre>{`[preview] Repository fetched: ${repo}
[preview] Isolated environment prepared
[preview] Model connection established
[preview] Task: create and run FizzBuzz for 1–15
[preview] Output matches all 15 expected values
[preview] Setup check passed

This is an example log, not an actual execution trace.`}</pre>
          </details>
        </div>
      </div>
      <div className="result-links">
        <Link className="text-link" to="/runs">View evaluations</Link>
        <button onClick={() => { setResult(null); navigate('/check') }}>Run again</button>
        <Link to="/import" className="text-link">Choose another harness</Link>
      </div>
    </FlowLayout>
  )
}
