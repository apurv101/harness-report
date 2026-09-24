import { STAGES } from '../../lib/preview'
import { Icon } from '../ui/Icon'

/**
 * The stages of a run: done, running, or still queued.  The preview walks its four simulated stages; a real run
 * passes its own, with a line of detail under each (the commit, the Docker setup, the live model calls, the tests).
 */
export function CheckStages({ completed, stages = STAGES, details, failed = false }: {
  completed: number
  stages?: readonly (readonly [string, string])[]
  details?: (string | null)[]
  failed?: boolean
}) {
  return (
    <div className="check-status">
      {stages.map(([title, desc], i) => {
        const done = i < completed
        const active = i === completed
        const stopped = active && failed
        return (
          <div key={title} className={`check-stage ${done ? 'done' : active ? 'active' : ''}`}>
            <span className="check-stage-indicator">
              {done ? <Icon name="check" /> : stopped ? <span>×</span> : active ? <span className="spinner" /> : <span>·</span>}
            </span>
            <div>
              <strong>{title}</strong>
              <small style={{ whiteSpace: 'pre-line', overflowWrap: 'anywhere' }}>{details?.[i] || desc}</small>
            </div>
            <span>{done ? 'DONE' : stopped ? 'STOPPED' : active ? 'RUNNING' : 'QUEUED'}</span>
          </div>
        )
      })}
    </div>
  )
}
