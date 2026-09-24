import { Link, useNavigate } from 'react-router-dom'
import { FlowLayout } from '../components/onboarding/FlowLayout'
import { SelectedRepo } from '../components/onboarding/SelectedRepo'
import { Icon } from '../components/ui/Icon'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { FIZZBUZZ_OUTPUT } from '../lib/preview'
import { usePreview } from '../state/PreviewContext'

const CHECKS = ['Repository fetched', 'Model connection verified', 'Environment prepared', 'Output matches expected result']

const FACTS = [['TASK RESULT', 'Passed'], ['MODEL CALLS', '6'], ['RUN TIME', '21s']] as const

/** The example report the preview ends on.  Every number here is illustrative. */
export function ResultPage() {
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
