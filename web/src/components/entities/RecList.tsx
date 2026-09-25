import { Link } from 'react-router-dom'
import type { Rec } from '../../lib/types'
import { Icon } from '../ui/Icon'

const seg = encodeURIComponent

/**
 * The tests recommended next, each with why.  `onRun` makes each one startable in place (the result page);
 * without it each links to the flow with the task preselected (a harness page, read by anyone).
 */
export function RecList({ recs, repo, onRun, busy }: {
  recs: Rec[]
  repo?: string | null
  onRun?: (rec: Rec) => void
  busy?: boolean
}) {
  return (
    <ol className="rec-list">
      {recs.map(r => (
        <li key={`${r.taskset}/${r.task}`} className="rec">
          <div className="rec-main">
            <Link className="rec-name" to={`/tasks/${seg(r.taskset)}/${seg(r.task)}`}>{r.task}</Link>
            <span className="rec-set">{r.taskset}{r.domain ? ` · ${r.domain}` : ''}{r.language ? ` · ${r.language}` : ''}</span>
            {r.why && <p className="rec-why">{r.why}</p>}
          </div>
          {onRun
            ? <button className="ui-btn small" disabled={busy} onClick={() => onRun(r)}><Icon name="play" /> Run this</button>
            : repo && <Link className="ui-btn small" to={`/check?${new URLSearchParams({ repo, taskset: r.taskset, task: r.task })}`}><Icon name="play" /> Run</Link>}
        </li>
      ))}
    </ol>
  )
}
