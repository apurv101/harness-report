import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { CheckStages } from '../components/onboarding/CheckStages'
import { FlowHeading, FlowLayout } from '../components/onboarding/FlowLayout'
import { SelectedRepo } from '../components/onboarding/SelectedRepo'
import { Icon } from '../components/ui/Icon'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { useSimulatedRun } from '../hooks/useSimulatedRun'
import { FIZZBUZZ_OUTPUT, STAGES } from '../lib/preview'
import { usePreview } from '../state/PreviewContext'

/** Step 3.  One small task to prove the loop works, end to end — simulated, and it says so. */
export function CheckPage() {
  useDocumentTitle('Run your first task · Harness Report')
  const { repo, setResult } = usePreview()
  const navigate = useNavigate()
  const [running, setRunning] = useState(false)
  const { completed, announcement } = useSimulatedRun(running, () => {
    setResult('example-passed')
    navigate('/check/result')
  })

  if (running) return <RunningCheck repo={repo!} completed={completed} announcement={announcement} onCancel={() => setRunning(false)} />

  return (
    <FlowLayout step={3}>
      <FlowHeading step={3} title="Run your first task." text="Start with FizzBuzz, then build from there." />
      <SelectedRepo repo={repo!} />
      <div className="flow-card">
        <div className="check-card-header">
          <span className="task-symbol"><Icon name="terminal" /></span>
          <div><h3>FizzBuzz</h3><p>A quick first run.</p></div>
        </div>
        <div className="check-card-body">
          <p className="task-description">Create a Python program that prints FizzBuzz from 1 to 15, then run it.</p>
          <div className="expected-output"><span>EXPECTED OUTPUT</span><code>{FIZZBUZZ_OUTPUT}</code></div>
        </div>
        <div className="check-actions">
          <span>Simulated run</span>
          <button className="ui-btn primary" onClick={() => setRunning(true)}><Icon name="play" /> Run task</button>
        </div>
      </div>
    </FlowLayout>
  )
}

function RunningCheck({ repo, completed, announcement, onCancel }: {
  repo: string
  completed: number
  announcement: string
  onCancel: () => void
}) {
  return (
    <FlowLayout step={3}>
      <FlowHeading step={3} title="Running FizzBuzz…" text="Follow your agent’s progress." />
      <SelectedRepo repo={repo} change={false} />
      <div className="flow-card" aria-busy="true">
        <div className="check-card-header">
          <span className="task-symbol"><Icon name="terminal" /></span>
          <div><h3>FizzBuzz</h3><p>Simulated run · {repo.split('/')[1]}</p></div>
        </div>
        <div className="check-progress" role="progressbar" aria-label="Setup check progress"
             aria-valuemin={0} aria-valuemax={STAGES.length} aria-valuenow={completed}>
          <div style={{ width: completed ? `${completed * 25}%` : '5%' }} />
        </div>
        <CheckStages completed={completed} />
        <div className="live-note" role="status" aria-live="polite">{announcement}</div>
      </div>
      <p className="flow-helper"><button className="ui-btn small" onClick={onCancel}>Cancel run</button></p>
    </FlowLayout>
  )
}
