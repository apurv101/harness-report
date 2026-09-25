import { Link, useParams, useSearchParams } from 'react-router-dom'
import { LoadError } from '../components/runs/LoadError'
import { OriginFacts, ResultFacts } from '../components/runs/RunFacts'
import { RunsShell } from '../components/runs/RunsShell'
import { KindPill, RewardCell, StatusPill, TestsCell } from '../components/runs/RunStatus'
import { RunTabs, type Tab } from '../components/runs/RunTabs'
import { CallsTab } from '../components/runs/tabs/CallsTab'
import { FilesTab } from '../components/runs/tabs/FilesTab'
import { LogsTab } from '../components/runs/tabs/LogsTab'
import { RecipeTab } from '../components/runs/tabs/RecipeTab'
import { RunJsonTab } from '../components/runs/tabs/RunJsonTab'
import { TimelineTab } from '../components/runs/tabs/TimelineTab'
import { TrajectoryTab } from '../components/runs/tabs/TrajectoryTab'
import { VerifierTab } from '../components/runs/tabs/VerifierTab'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { useRunBundle } from '../hooks/useRunBundle'

/** One run folder, whole: what it was asked to do, what the model did, and how it was judged. */
export function RunDetailPage() {
  const { runId = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const { bundle, error, live, reload } = useRunBundle(runId)

  useDocumentTitle(bundle ? `${bundle.run} · ${bundle.run_json.harness?.name || ''}` : 'Harness Report')

  const crumb = <><Link to="/runs">Evaluations</Link> / {runId}</>
  const seg = encodeURIComponent
  if (error && !bundle) return <RunsShell crumb={crumb}><LoadError message={error} onRetry={reload} /></RunsShell>
  if (!bundle) return <RunsShell crumb={crumb}><p className="empty" role="status">Loading results…</p></RunsShell>

  const run = bundle.run_json
  const harness = run.harness || {}
  const harbor = run.kind === 'harbor'

  const tabs: Tab[] = [
    { id: 'all', label: 'Timeline', count: bundle.calls.length + (bundle.egress?.length || 0),
      panel: () => <TimelineTab bundle={bundle} live={live} /> },
    { id: 'traj', label: 'Trajectory', panel: () => <TrajectoryTab calls={bundle.calls} /> },
    { id: 'calls', label: 'Calls', count: bundle.calls.length, panel: () => <CallsTab calls={bundle.calls} /> },
    ...(harbor ? [{ id: 'verifier', label: 'Verifier', panel: () => <VerifierTab bundle={bundle} /> }] : []),
    { id: 'logs', label: 'Logs', panel: () => <LogsTab bundle={bundle} /> },
    { id: 'recipe', label: 'Recipe', panel: () => <RecipeTab bundle={bundle} /> },
    { id: 'run', label: 'run.json', panel: () => <RunJsonTab run={run} /> },
    { id: 'files', label: 'Files', count: bundle.files.length, panel: () => <FilesTab bundle={bundle} /> },
  ]

  return (
    <RunsShell crumb={crumb}>
      <h1 className="mono" tabIndex={-1}>{bundle.run}</h1>
      <div className="muted">
        <KindPill run={run} />{' '}
        {harness.repo
          ? <a href={`${harness.repo}${harness.commit ? `/tree/${harness.commit}` : ''}`} target="_blank" rel="noopener">
              {harness.repo.replace('https://github.com/', '')}
            </a>
          : '—'}
        {harness.commit && <> <span className="mono small">@ {harness.commit.slice(0, 10)}</span></>}
        {harness.name && <> · <Link to={`/harnesses/${seg(harness.name)}`}>{harness.name}</Link></>}
        {harbor && run.task?.name && <> · <Link to={`/tasks/${seg(run.task.taskset || '')}/${seg(run.task.name)}`}>{run.task.taskset} / {run.task.name}</Link></>}
        {' · '}<StatusPill run={run} />
        {live && <> · <span className="tl-live">● following, updating every 3s</span></>}
        {harbor && <>
          {' · reward '}<RewardCell run={run} />
          {(run.tests?.total || run.tests?.aborted) ? <>{' · tests '}<TestsCell tests={run.tests} /></> : null}
        </>}
      </div>

      <OriginFacts bundle={bundle} />
      <ResultFacts bundle={bundle} />

      <h2>{harbor ? 'Instruction' : 'Prompt'}</h2>
      <div className="task">{bundle.task || run.prompt || '(no task.txt)'}</div>

      <RunTabs tabs={tabs} selected={params.get('tab') || 'all'}
               onSelect={id => setParams({ tab: id }, { replace: true })} />
    </RunsShell>
  )
}
