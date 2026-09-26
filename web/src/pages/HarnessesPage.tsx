import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Twins } from '../components/entities/Outcome'
import { LoadError } from '../components/runs/LoadError'
import { RunsShell } from '../components/runs/RunsShell'
import { EmptyCard } from '../components/ui/EmptyCard'
import { SearchInput } from '../components/ui/SearchInput'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { useJSON } from '../hooks/useJSON'
import { getHarnesses } from '../lib/api'
import { truncate } from '../lib/format'

/** Every harness that has been run here, in the order the server lists them (most runs first). */
export function HarnessesPage() {
  useDocumentTitle('Harnesses · Harness Report')
  const [query, setQuery] = useState('')
  const { data, error, reload } = useJSON(getHarnesses, [], 'Harness data is unavailable. Try again.')
  const crumb = <><Link to="/">Home</Link> / Harnesses</>
  if (error) return <RunsShell crumb={crumb}><LoadError message={error} onRetry={reload} /></RunsShell>
  if (!data) return <RunsShell crumb={crumb}><p className="empty" role="status">Loading harnesses…</p></RunsShell>

  const q = query.trim().toLowerCase()
  const rows = data.harnesses.filter(h => [h.harness, h.use_case, h.summary, h.repo].join(' ').toLowerCase().includes(q))
  return (
    <RunsShell crumb={crumb}>
      <div className="run-list-head">
        <div>
          <h1 tabIndex={-1}>Harnesses</h1>
          <p>{data.harnesses.length} agent harnesses reviewed or evaluated from their GitHub repos</p>
        </div>
        <Link className="ui-btn primary" to="/connect">Evaluate yours ↗</Link>
      </div>
      <SearchInput value={query} onChange={setQuery} label="Search harnesses" placeholder="Search harnesses…" />
      {rows.length ? (
        <div className="run-table" role="region" aria-label="Harnesses" tabIndex={0}>
          <table>
            <thead><tr><th>Harness</th><th>What it is for</th><th className="num">Runs</th><th className="num">Tasks tried</th><th>Last run</th></tr></thead>
            <tbody>
              {rows.map(h => (
                <tr key={h.harness}>
                  <td><Link className="run-name" to={`/harnesses/${encodeURIComponent(h.harness)}`}>{h.harness}</Link>
                    {h.repo && <span className="run-id">{h.repo.replace('https://github.com/', '')}</span>}</td>
                  <td className="run-task">{truncate(h.use_case || h.summary || '', 110)}
                    {h.compatibility?.status === 'blocked' && <span className="run-id">Needs integration</span>}</td>
                  <td className="num">{h.runs}</td>
                  <td className="num">{h.tasks_tried}</td>
                  <td className="mono small">{(h.last_run || '').slice(0, 10)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <EmptyCard role="status">No matching harnesses.</EmptyCard>}
      <Twins path="/harnesses" />
    </RunsShell>
  )
}
