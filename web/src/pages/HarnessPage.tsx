import { Link, useParams } from 'react-router-dom'
import { OutcomesCell, Twins } from '../components/entities/Outcome'
import { RecList } from '../components/entities/RecList'
import { RunRows } from '../components/entities/RunRows'
import { LoadError } from '../components/runs/LoadError'
import { RunsShell } from '../components/runs/RunsShell'
import { Fact, Facts } from '../components/ui/Fact'
import { Pill } from '../components/ui/Pill'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { useJSON } from '../hooks/useJSON'
import { getHarness } from '../lib/api'
import { shortModel } from '../lib/format'

const seg = encodeURIComponent

/** One harness: what it is for, how it runs here, how it did on every task, and what to run next. */
export function HarnessPage() {
  const { name = '' } = useParams()
  useDocumentTitle(`${name} · Harness Report`)
  const { data, error, reload } = useJSON(signal => getHarness(name, signal), [name], 'No such harness, or the data is unavailable.')
  const crumb = <><Link to="/harnesses">Harnesses</Link> / {name}</>
  if (error) return <RunsShell crumb={crumb}><LoadError message={error} onRetry={reload} /></RunsShell>
  if (!data) return <RunsShell crumb={crumb}><p className="empty" role="status">Loading…</p></RunsShell>

  const h = data.harness; const p = data.profile; const recs = data.recommendations
  const repo = h.repo?.replace('https://github.com/', '') || null
  const results = Object.entries(h.results || {}).sort(([a], [b]) => a.localeCompare(b))
  return (
    <RunsShell crumb={crumb}>
      <h1 tabIndex={-1}>{h.harness}</h1>
      {p?.use_case && <p className="lede">{p.use_case}</p>}
      <div className="muted">
        {h.repo && <a href={`${h.repo}${h.commit ? `/tree/${h.commit}` : ''}`} target="_blank" rel="noopener">{repo}</a>}
        {h.commit && <> <span className="mono small">@ {h.commit.slice(0, 10)}</span></>}
        {(p?.domains || []).map(d => <span key={d}> <Pill>{d}</Pill></span>)}
        {(p?.languages || []).map(l => <span key={l}> <Pill>{l}</Pill></span>)}
      </div>
      <Facts>
        <Fact name="runs" value={h.runs} />
        <Fact name="with a reward" value={`${h.scored ?? 0} of ${h.finished}`} />
        <Fact name="tasks tried" value={h.tasks_tried} />
        <Fact name="tasksets" value={(h.tasksets || []).join(', ')} />
        <Fact name="api" value={h.api_style} />
        <Fact name="model" value={(h.models || []).map(shortModel).join(', ')} />
      </Facts>

      <h2>Tests to run next</h2>
      {recs?.recs?.length
        ? <>
            <p className="muted small">Picked for what {h.harness} is for{recs.source === 'llm' ? ', by a model reading its profile and results' : ', by rules on its profile and results'}.</p>
            <RecList recs={recs.recs} repo={repo} />
          </>
        : <p className="muted">Recommendations appear after the first run.</p>}

      <h2>Results by task</h2>
      {results.length ? (
        <div className="run-table" role="region" aria-label="Results by task" tabIndex={0}>
          <table>
            <thead><tr><th>Task</th><th>Verifier says (latest run)</th><th>Last run</th></tr></thead>
            <tbody>
              {results.map(([key, o]) => {
                const [ts, task] = key.split('/')
                return (
                  <tr key={key}>
                    <td><Link to={`/tasks/${seg(ts)}/${seg(task)}`}>{task}</Link><span className="run-id">{ts}</span></td>
                    <td><OutcomesCell o={o} /></td>
                    <td>{o.last_run ? <Link className="mono small" to={`/runs/${seg(o.last_run)}`}>{(o.last || '').slice(0, 16).replace('T', ' ')}</Link> : '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : <p className="muted">No Harbor tasks run yet.</p>}

      {h.summary && <><h2>How it runs here</h2><p className="prose">{h.summary}</p></>}
      {p?.evidence && <p className="muted small">Profile based on: {p.evidence}</p>}

      <h2>Runs</h2>
      <RunRows runs={data.runs} show="task" />
      <Twins path={`/harnesses/${seg(h.harness)}`} />
    </RunsShell>
  )
}
