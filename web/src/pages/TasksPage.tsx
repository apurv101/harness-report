import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Twins } from '../components/entities/Outcome'
import { LoadError } from '../components/runs/LoadError'
import { RunsShell } from '../components/runs/RunsShell'
import { EmptyCard } from '../components/ui/EmptyCard'
import { Pill } from '../components/ui/Pill'
import { SearchInput } from '../components/ui/SearchInput'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { useJSON } from '../hooks/useJSON'
import { getTasksets } from '../lib/api'

/** Every indexed Harbor taskset, runnable ones first, filterable by domain. */
export function TasksPage() {
  useDocumentTitle('Tasks · Harness Report')
  const [query, setQuery] = useState('')
  const [domain, setDomain] = useState('')
  const [runnable, setRunnable] = useState(false)
  const { data, error, reload } = useJSON(getTasksets, [], 'Task data is unavailable. Try again.')
  const crumb = <><Link to="/">Home</Link> / Tasks</>
  if (error) return <RunsShell crumb={crumb}><LoadError message={error} onRetry={reload} /></RunsShell>
  if (!data) return <RunsShell crumb={crumb}><p className="empty" role="status">Loading tasks…</p></RunsShell>

  const q = query.trim().toLowerCase()
  const rows = data.tasksets.filter(t => (!domain || t.domain === domain) && (!runnable || t.n_runnable)
    && [t.taskset, t.name, t.domain, t.task_kind, t.owner_org, ...(t.languages || []), ...(t.categories || [])].join(' ').toLowerCase().includes(q))
  const total = data.tasksets.reduce((a, t) => a + (t.n_tasks || 0), 0)
  const live = data.tasksets.reduce((a, t) => a + (t.n_runnable || 0), 0)
  return (
    <RunsShell crumb={crumb}>
      <div className="run-list-head">
        <div>
          <h1 tabIndex={-1}>Tasks</h1>
          <p>{data.tasksets.length} Harbor tasksets · {total.toLocaleString()} tasks · {live} runnable from this site</p>
        </div>
      </div>
      <div className="filter-row">
        <SearchInput value={query} onChange={setQuery} label="Search tasksets" placeholder="Search tasksets, languages, domains…" />
        <select aria-label="Domain" value={domain} onChange={e => setDomain(e.target.value)}>
          <option value="">All domains</option>
          {data.domains.map(d => <option key={d} value={d}>{d}</option>)}
        </select>
        <label className="check-label"><input type="checkbox" checked={runnable} onChange={e => setRunnable(e.target.checked)} /> Runnable here</label>
      </div>
      {rows.length ? (
        <div className="run-table" role="region" aria-label="Tasksets" tabIndex={0}>
          <table>
            <thead><tr><th>Taskset</th><th>Domain</th><th className="num">Tasks</th><th className="num">Runnable</th><th>Languages</th><th>Grading</th></tr></thead>
            <tbody>
              {rows.map(t => (
                <tr key={t.taskset}>
                  <td><Link className="run-name" to={`/tasks/${encodeURIComponent(t.taskset)}`}>{t.taskset}</Link>
                    {(t.owner_org || t.task_kind) && <span className="run-id">{[t.owner_org, t.task_kind].filter(Boolean).join(' · ')}</span>}</td>
                  <td>{t.domain || '—'}</td>
                  <td className="num">{t.n_tasks.toLocaleString()}</td>
                  <td className="num">{t.n_runnable ? <Pill tone="ok">{t.n_runnable}</Pill> : '—'}</td>
                  <td className="small">{(t.languages || []).slice(0, 6).join(', ') || '—'}</td>
                  <td className="small">{t.grading || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <EmptyCard role="status">No matching tasksets.</EmptyCard>}
      <Twins path="/tasks" />
    </RunsShell>
  )
}
