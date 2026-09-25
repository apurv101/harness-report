import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Twins } from '../components/entities/Outcome'
import { LoadError } from '../components/runs/LoadError'
import { RunsShell } from '../components/runs/RunsShell'
import { Fact, Facts } from '../components/ui/Fact'
import { Pill } from '../components/ui/Pill'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { getTaskset } from '../lib/api'
import type { TaskCard, TasksetCard } from '../lib/types'

const seg = encodeURIComponent

/** One taskset: where it comes from, and its tasks a page at a time (the largest has 33,786). */
export function TasksetPage() {
  const { taskset = '' } = useParams()
  useDocumentTitle(`${taskset} · Harness Report`)
  const [card, setCard] = useState<TasksetCard | null>(null)
  const [tasks, setTasks] = useState<TaskCard[]>([])
  const [next, setNext] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = (after: string | null, signal?: AbortSignal) => {
    setLoading(true)
    getTaskset(taskset, after, signal)
      .then(d => { setCard(d.taskset); setTasks(prev => after ? [...prev, ...d.tasks] : d.tasks); setNext(d.next); setError(null) })
      .catch((e: Error) => { if (e.name !== 'AbortError') setError('No such taskset, or the data is unavailable.') })
      .finally(() => setLoading(false))
  }
  useEffect(() => {
    const ac = new AbortController()
    setCard(null); setTasks([]); setNext(null)
    load(null, ac.signal)
    return () => ac.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskset])

  const crumb = <><Link to="/tasks">Tasks</Link> / {taskset}</>
  if (error && !card) return <RunsShell crumb={crumb}><LoadError message={error} onRetry={() => load(null)} /></RunsShell>
  if (!card) return <RunsShell crumb={crumb}><p className="empty" role="status">Loading…</p></RunsShell>
  return (
    <RunsShell crumb={crumb}>
      <h1 tabIndex={-1}>{card.taskset}</h1>
      {card.name && card.name !== card.taskset && <p className="lede">{card.name}{card.task_kind ? ` — ${card.task_kind}` : ''}</p>}
      <div className="muted">
        {card.url_repo && <a href={card.url_repo} target="_blank" rel="noopener">source</a>}
        {card.url_paper && <> · <a href={card.url_paper} target="_blank" rel="noopener">paper</a></>}
      </div>
      <Facts>
        <Fact name="tasks" value={card.n_tasks.toLocaleString()} />
        <Fact name="runnable here" value={card.n_runnable} />
        <Fact name="domain" value={card.domain} />
        <Fact name="owner" value={card.owner_org} />
        <Fact name="grading" value={card.grading} />
        <Fact name="languages" value={(card.languages || []).join(', ')} />
      </Facts>
      <h2>Tasks</h2>
      <div className="run-table" role="region" aria-label="Tasks" tabIndex={0}>
        <table>
          <thead><tr><th>Task</th><th>Difficulty</th><th>Language</th><th>Runnable</th><th className="num">Harnesses tried</th></tr></thead>
          <tbody>
            {tasks.map(t => {
              const res = Object.values(t.results || {})
              return (
                <tr key={t.task}>
                  <td><Link to={`/tasks/${seg(card.taskset)}/${seg(t.task)}`}>{t.task}</Link></td>
                  <td className="small">{t.difficulty || '—'}</td>
                  <td className="small">{t.language || '—'}</td>
                  <td>{t.runnable ? <Pill tone="ok">runnable</Pill> : t.compose ? <Pill tone="warn">multi-container</Pill> : '—'}</td>
                  <td className="num">{res.length || '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {next && <p><button className="ui-btn small" disabled={loading} onClick={() => load(next)}>{loading ? 'Loading…' : 'Show more tasks'}</button></p>}
      <Twins path={`/tasks/${seg(card.taskset)}`} />
    </RunsShell>
  )
}
