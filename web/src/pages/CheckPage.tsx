import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { CheckStages } from '../components/onboarding/CheckStages'
import { FlowHeading, FlowLayout } from '../components/onboarding/FlowLayout'
import { LiveArtifacts } from '../components/onboarding/LiveArtifacts'
import { LiveConsole } from '../components/onboarding/LiveConsole'
import { SelectedRepo } from '../components/onboarding/SelectedRepo'
import { Icon } from '../components/ui/Icon'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { useEvaluation } from '../hooks/useEvaluation'
import { useSimulatedRun } from '../hooks/useSimulatedRun'
import { cancelEval, getCurrentEval, getFirstTask, getTask, startEval } from '../lib/api'
import { BOWLING, inProgress, LIVE_STAGES, progress, taskTitle } from '../lib/evaluation'
import type { FirstTask, Rec, TaskCard } from '../lib/types'
import { FIZZBUZZ_OUTPUT, STAGES } from '../lib/preview'
import { usePreview } from '../state/PreviewContext'
import { useServed } from '../state/SessionContext'

/**
 * Step 3.  One task to prove the loop works end to end.  With serve.py behind the page it is real: run.sh on the
 * chosen repository and the task picked for it (its recommendations, or a guess from the repo), followed live.  On the static site it is the simulated FizzBuzz, and says so.
 */
export function CheckPage() {
  useDocumentTitle('Run your first task · Harness Report')
  const served = useServed()
  if (served === null) return <FlowLayout step={3}><FlowHeading step={3} title="Run your first task." text="" /></FlowLayout>
  return served ? <LiveCheck /> : <PreviewCheck />
}

function LiveCheck() {
  const { repo: chosen, repoMeta, selectRepo, setEval } = usePreview()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  // A /check?repo=…&taskset=…&task=… link (a harness page, a task page, MCP's run_url) names the run outright.
  const repo = params.get('repo') || chosen!
  const named = params.get('taskset') && params.get('task') ? { taskset: params.get('taskset')!, task: params.get('task')! } : null
  const [evalId, setEvalId] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [busyWith, setBusyWith] = useState<string | null>(null)
  const [first, setFirst] = useState<FirstTask | null>(null)
  const [pick, setPick] = useState<Rec | null>(named)
  const [card, setCard] = useState<TaskCard | null>(null)

  const adopted = useRef(false)
  useEffect(() => {
    if (!adopted.current && repo && repo !== chosen) { adopted.current = true; selectRepo(repo) }
  }, [repo, chosen, selectRepo])

  // One evaluation at a time on this machine: if one is already running (this tab refreshed, or another tab
  // started it), follow it instead of offering a second.
  useEffect(() => {
    const ac = new AbortController()
    getCurrentEval(ac.signal).then(cur => {
      if (!cur) return
      if (cur.eval.repo.toLowerCase() === repo.toLowerCase()) setEvalId(cur.eval.id)
      else setBusyWith(cur.eval.repo)
    }).catch(() => { /* the button reports any real problem */ })
    return () => ac.abort()
  }, [repo])

  // What to run first: the task a link named, else this harness's top recommendation, else a guess from the
  // repository's language and description.  Bowling only when the server has nothing to say.
  useEffect(() => {
    const ac = new AbortController()
    getFirstTask(repo, repoMeta || undefined, ac.signal)
      .then(f => { setFirst(f); if (!named) setPick(f ? { ...f } : BOWLING) })
      .catch(() => { if (!named) setPick(BOWLING) })
    return () => ac.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repo])

  useEffect(() => {
    if (!pick) return
    const ac = new AbortController()
    setCard(null)
    getTask(pick.taskset, pick.task, ac.signal).then(d => setCard(d.task)).catch(() => { /* the card still shows the name */ })
    return () => ac.abort()
  }, [pick])

  const start = async () => {
    setStarting(true); setProblem(null)
    try { const s = await startEval(repo, pick); setEvalId(s.eval.id) }
    catch (e) { setProblem(e instanceof Error ? e.message : String(e)) }
    finally { setStarting(false) }
  }

  if (evalId) return <RunningLive id={evalId} onFinished={id => { setEval(id); navigate('/check/result') }} />

  const others = (first?.recs || []).filter(r => !pick || r.taskset !== pick.taskset || r.task !== pick.task).slice(0, 4)
  const why = named ? 'The task you picked.' : pick?.why ? `Picked for your harness: ${pick.why.replace(/[.\s]+$/, '')}.` : null
  const excerpt = (card?.instruction || '').replace(/^#.*$/gm, '').replace(/\s+/g, ' ').trim().slice(0, 260)
  return (
    <FlowLayout step={3}>
      <FlowHeading step={3} title="Run your first task." text="Your harness on one real benchmark task, with its tests." />
      <SelectedRepo repo={repo} />
      <div className="flow-card">
        <div className="check-card-header">
          <span className="task-symbol"><Icon name="terminal" /></span>
          <div><h3>{pick ? taskTitle(pick.task) : 'Choosing a task…'}</h3><p>{pick ? `${pick.taskset} · ${pick.task}` : ''}</p></div>
        </div>
        <div className="check-card-body">
          {why && <p className="task-why">{why}</p>}
          <p className="task-description">{excerpt ? `${excerpt}${excerpt.length >= 260 ? '…' : ''}` : ' '}</p>
          <div className="expected-output"><span>HOW IT IS SCORED</span><code>The task’s own tests run after your agent finishes, in a container it never saw. It passes when they all pass.</code></div>
          {pick && <p className="flow-helper" style={{ textAlign: 'left', margin: '10px 0 0' }}>
            <Link className="text-link" to={`/tasks/${encodeURIComponent(pick.taskset)}/${encodeURIComponent(pick.task)}`}>Read the whole task</Link>
          </p>}
        </div>
        <div className="check-actions">
          <span>{busyWith ? `${busyWith} is running now. One run at a time.` : problem || 'Runs as linux/amd64'}</span>
          <button className="ui-btn primary" onClick={start} disabled={starting || !!busyWith || !pick}>
            <Icon name="play" /> {starting ? 'Starting…' : 'Run task'}
          </button>
        </div>
      </div>
      {!!others.length && (
        <div className="alt-tasks">
          <p className="muted small">Or start with</p>
          <div>{others.map(r => (
            <button key={`${r.taskset}/${r.task}`} className="ui-btn small" onClick={() => setPick(r)} title={r.why || ''}>
              {taskTitle(r.task)} <span className="muted">· {r.taskset}</span>
            </button>
          ))}</div>
        </div>
      )}
      {busyWith && <p className="flow-helper"><Link className="text-link" to="/runs">See the run in progress</Link></p>}
    </FlowLayout>
  )
}

function RunningLive({ id, onFinished }: { id: string; onFinished: (id: string) => void }) {
  const { state, events, error } = useEvaluation(id)
  const [cancelling, setCancelling] = useState(false)
  const status = state?.eval.status
  // exactly once: onFinished updates the flow state, which re-renders this with a new onFinished
  const finished = useRef(false)
  useEffect(() => {
    if (status && !inProgress(status) && !finished.current) { finished.current = true; onFinished(id) }
  }, [status, id, onFinished])

  const { completed, details, error: stopped } = progress(events, state?.live ?? null, state)
  const repo = state?.eval.repo || ''
  const last = [...events].reverse().find(e => e.type === 'stage')
  const title = taskTitle(state?.eval.task)
  const note = error ? `Lost contact with serve.py (${error}). The run continues; retrying…`
    : stopped ? `Stopped: ${stopped}`
    : status === 'queued' ? 'Waiting for a runner to pick it up…'
    : last ? `${last.t ?? 0}s · ${last.stage}: ${(last.msg || '').split('\n')[0].slice(0, 160)}`
    : 'Starting run.sh…'

  return (
    <FlowLayout step={3}>
      <FlowHeading step={3} title={`Running ${title}…`} text="Follow your agent’s progress. This page can be closed; the run keeps going." />
      {repo && <SelectedRepo repo={repo} change={false} />}
      <div className="flow-card" aria-busy={inProgress(status)}>
        <div className="check-card-header">
          <span className="task-symbol"><Icon name="terminal" /></span>
          <div><h3>{title}</h3><p>{state?.eval.taskset} · live run · {id}</p></div>
        </div>
        <div className="check-progress" role="progressbar" aria-label="Run progress"
             aria-valuemin={0} aria-valuemax={LIVE_STAGES.length} aria-valuenow={completed}>
          <div style={{ width: `${Math.max(5, (completed / LIVE_STAGES.length) * 100)}%` }} />
        </div>
        <CheckStages completed={completed} stages={LIVE_STAGES} details={details} failed={!!stopped} />
        <div className="live-note" role="status" aria-live="polite" style={{ overflowWrap: 'anywhere' }}>{note}</div>
        {/* the stage list says where the run is; these two say what it is doing and what it has written */}
        <LiveConsole id={id} />
        {state?.eval.run && <LiveArtifacts run={state.eval.run} running={status === 'running'} />}
      </div>
      <p className="flow-helper">
        <button className="ui-btn small" disabled={cancelling || !inProgress(status)}
                onClick={async () => { setCancelling(true); try { await cancelEval(id) } catch { setCancelling(false) } }}>
          {cancelling ? 'Cancelling…' : 'Cancel run'}
        </button>
      </p>
    </FlowLayout>
  )
}

function PreviewCheck() {
  const { repo, setResult } = usePreview()
  const navigate = useNavigate()
  const [running, setRunning] = useState(false)
  const { completed, announcement } = useSimulatedRun(running, () => {
    setResult('example-passed')
    navigate('/check/result')
  })

  if (running) return <RunningPreview repo={repo!} completed={completed} announcement={announcement} onCancel={() => setRunning(false)} />

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

function RunningPreview({ repo, completed, announcement, onCancel }: {
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
