import { useState } from 'react'
import { Link } from 'react-router-dom'
import { LoadError } from '../components/runs/LoadError'
import { RunsShell } from '../components/runs/RunsShell'
import { RunsTable } from '../components/runs/RunsTable'
import { EmptyCard } from '../components/ui/EmptyCard'
import { SearchInput } from '../components/ui/SearchInput'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { useJSON } from '../hooks/useJSON'
import { getRuns } from '../lib/api'
import { taskText } from '../lib/format'
import type { RunSummary } from '../lib/types'

/** Every run under runs/, newest first, searchable by harness, task, run id, or model. */
export function RunsPage() {
  useDocumentTitle('Evaluations · Harness Report')
  const [query, setQuery] = useState('')
  const { data: runs, error, reload } = useJSON<RunSummary[]>(
    getRuns, [], 'Run data is unavailable. Check the local server and try again.')

  if (error) return <RunsShell crumb={<><Link to="/">Home</Link> / Evaluations</>}><LoadError message={error} onRetry={reload} /></RunsShell>
  if (!runs) return <RunsShell crumb={<><Link to="/">Home</Link> / Evaluations</>}><p className="empty" role="status">Loading results…</p></RunsShell>

  const matches = runs.filter(r =>
    [r.run, r.harness?.name, taskText(r), r.model].join(' ').toLowerCase().includes(query.trim().toLowerCase()))

  return (
    <RunsShell crumb={<><Link to="/">Home</Link> / Evaluations</>}>
      <div className="run-list-head">
        <div>
          <h1 tabIndex={-1}>Evaluations</h1>
          <p>{runs.length} recorded run{runs.length === 1 ? '' : 's'}</p>
        </div>
        <Link className="ui-btn primary" to="/connect">Connect harness ↗</Link>
      </div>
      {!runs.length ? (
        <EmptyCard>
          <h2>No runs yet</h2>
          <p>Your recorded evaluations will appear here.</p>
          <Link className="ui-btn" to="/connect">Connect your harness</Link>
        </EmptyCard>
      ) : (
        <>
          <SearchInput value={query} onChange={setQuery}
                       label="Search runs" placeholder="Search harnesses, tasks, or runs…" />
          {matches.length ? <RunsTable runs={matches} /> : <EmptyCard role="status">No matching runs.</EmptyCard>}
        </>
      )}
    </RunsShell>
  )
}
