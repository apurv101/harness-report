import { Link } from 'react-router-dom'
import { fmt } from '../../lib/format'
import type { RunRow } from '../../lib/types'
import { OutcomePill } from './Outcome'

const seg = encodeURIComponent

/** Runs as a harness page or a task page lists them: whichever of harness / task the page is not about. */
export function RunRows({ runs, show }: { runs: RunRow[]; show: 'harness' | 'task' }) {
  if (!runs.length) return <p className="muted">No runs yet.</p>
  return (
    <div className="run-table" role="region" aria-label="Runs" tabIndex={0}>
      <table>
        <thead>
          <tr>
            <th>Run</th><th>{show === 'harness' ? 'Harness' : 'Task'}</th><th>Verifier says</th>
            <th className="num">Calls</th><th className="num">Time</th>
          </tr>
        </thead>
        <tbody>
          {runs.map(r => (
            <tr key={r.run}>
              <td><Link className="run-name mono" to={`/runs/${seg(r.run)}`}>{(r.started || r.run).replace('T', ' ').slice(0, 16)}</Link>
                <span className="run-id" title={r.run}>{r.run}</span></td>
              <td>{show === 'harness'
                ? r.harness ? <Link to={`/harnesses/${seg(r.harness)}`}>{r.harness}</Link> : '—'
                : r.task?.name ? <Link to={`/tasks/${seg(r.task.taskset || '')}/${seg(r.task.name)}`}>{r.task.taskset} / {r.task.name}</Link> : 'prompt'}</td>
              <td><OutcomePill run={r} /></td>
              <td className="num">{fmt(r.calls)}</td>
              <td className="num">{r.seconds == null ? '—' : `${r.seconds}s`}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
