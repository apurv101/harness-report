import { Link, useParams } from 'react-router-dom'
import { OutcomesCell, Twins } from '../components/entities/Outcome'
import { RunRows } from '../components/entities/RunRows'
import { LoadError } from '../components/runs/LoadError'
import { RunsShell } from '../components/runs/RunsShell'
import { Fact, Facts } from '../components/ui/Fact'
import { Icon } from '../components/ui/Icon'
import { Pill } from '../components/ui/Pill'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { useJSON } from '../hooks/useJSON'
import { getTask } from '../lib/api'
import { usePreview } from '../state/PreviewContext'

const seg = encodeURIComponent

/** One task: its instruction, whether the site can run it, and every harness's result on it. */
export function TaskPage() {
  const { taskset = '', task = '' } = useParams()
  useDocumentTitle(`${task} · ${taskset} · Harness Report`)
  const { repo } = usePreview()
  const { data, error, reload } = useJSON(signal => getTask(taskset, task, signal), [taskset, task], 'No such task, or the data is unavailable.')
  const crumb = <><Link to="/tasks">Tasks</Link> / <Link to={`/tasks/${seg(taskset)}`}>{taskset}</Link> / {task}</>
  if (error) return <RunsShell crumb={crumb}><LoadError message={error} onRetry={reload} /></RunsShell>
  if (!data) return <RunsShell crumb={crumb}><p className="empty" role="status">Loading…</p></RunsShell>

  const t = data.task
  const results = Object.entries(t.results || {}).sort(([, a], [, b]) => b.passes - a.passes)
  const run = new URLSearchParams({ ...(repo ? { repo } : {}), taskset: t.taskset, task: t.task })
  return (
    <RunsShell crumb={crumb}>
      <div className="run-list-head">
        <div>
          <h1 className="mono" tabIndex={-1}>{t.task}</h1>
          <p>{t.taskset}{t.category ? ` · ${t.category}` : ''} {t.runnable ? <Pill tone="ok">runnable here</Pill> : <Pill>not runnable here yet</Pill>}</p>
        </div>
        {t.runnable && <Link className="ui-btn primary" to={repo ? `/check?${run}` : '/connect'}><Icon name="play" /> Run on {repo ? repo.split('/')[1] : 'your harness'}</Link>}
      </div>
      <Facts>
        <Fact name="difficulty" value={t.difficulty} />
        <Fact name="language" value={t.language} />
        <Fact name="agent timeout" value={t.agent_timeout ? `${t.agent_timeout} s` : null} />
        <Fact name="reference solution" value={t.oracle ? `reward ${t.oracle.reward} on ${t.oracle.platform}` : null} />
        <Fact name="harnesses tried" value={results.length} />
      </Facts>
      <h2>Results by harness</h2>
      {results.length ? (
        <div className="run-table" role="region" aria-label="Results by harness" tabIndex={0}>
          <table>
            <thead><tr><th>Harness</th><th>Result</th><th>Last run</th></tr></thead>
            <tbody>
              {results.map(([h, o]) => (
                <tr key={h}>
                  <td><Link className="run-name" to={`/harnesses/${seg(h)}`}>{h}</Link></td>
                  <td><OutcomesCell o={o} /></td>
                  <td>{o.last_run ? <Link className="mono small" to={`/runs/${seg(o.last_run)}`}>{(o.last || '').slice(0, 16).replace('T', ' ')}</Link> : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="muted">No harness has run this task yet.</p>}
      <h2>Instruction</h2>
      <pre className="instruction">{(t.instruction || '').trim() || '—'}</pre>
      {t.instruction_truncated && <p className="muted small">Cut at 16k characters.</p>}
      <h2>Runs</h2>
      <RunRows runs={data.runs} show="harness" />
      <Twins path={`/tasks/${seg(t.taskset)}/${seg(t.task)}`} />
    </RunsShell>
  )
}
