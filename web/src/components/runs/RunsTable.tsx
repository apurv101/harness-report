import { Link, useNavigate } from 'react-router-dom'
import { fmt, taskText, truncate } from '../../lib/format'
import type { RunSummary } from '../../lib/types'
import { EvaluationStatus } from './RunStatus'

/** Every recorded run, newest first.  One row is one runs/<run-id>/run.json. */
export function RunsTable({ runs }: { runs: RunSummary[] }) {
  const navigate = useNavigate()

  const open = (event: React.MouseEvent, runId: string) => {
    const target = event.target as HTMLElement
    if (target.closest('a') || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return
    navigate(`/runs/${encodeURIComponent(runId)}`)
  }

  return (
    <div className="run-table" role="region" aria-label="Recorded evaluations" tabIndex={0}>
      <table>
        <thead>
          <tr>
            <th>Harness / run</th><th>Task</th><th>Result</th>
            <th className="num">Calls</th><th className="num">Tokens in / out</th><th className="num">Time</th>
          </tr>
        </thead>
        <tbody>
          {runs.map(run => (
            <tr className="row" key={run.run} onClick={e => open(e, run.run)}>
              <td>
                {run.harness?.name
                  ? <Link className="run-name" to={`/harnesses/${encodeURIComponent(run.harness.name)}`}>{run.harness.name}</Link>
                  : <Link className="run-name" to={`/runs/${encodeURIComponent(run.run)}`}>{run.run}</Link>}
                <span className="run-id" title={run.run}>{run.run}</span>
              </td>
              <td className="run-task">{run.kind === 'harbor' && run.task?.name
                ? <Link to={`/tasks/${encodeURIComponent(run.task.taskset || '')}/${encodeURIComponent(run.task.name)}`}>{truncate(taskText(run), 100)}</Link>
                : truncate(taskText(run), 100)}</td>
              <td><EvaluationStatus run={run} /></td>
              <td className="num">{fmt(run.calls)}</td>
              <td className="num">{fmt(run.input_tokens)} / {fmt(run.output_tokens)}</td>
              <td className="num">{run.seconds == null ? '—' : `${run.seconds}s`}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
