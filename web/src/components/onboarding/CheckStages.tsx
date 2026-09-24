import { STAGES } from '../../lib/preview'
import { Icon } from '../ui/Icon'

/** The four stages of the simulated run: done, running, or still queued. */
export function CheckStages({ completed }: { completed: number }) {
  return (
    <div className="check-status">
      {STAGES.map(([title, desc], i) => {
        const done = i < completed
        const active = i === completed
        return (
          <div key={title} className={`check-stage ${done ? 'done' : active ? 'active' : ''}`}>
            <span className="check-stage-indicator">
              {done ? <Icon name="check" /> : active ? <span className="spinner" /> : <span>·</span>}
            </span>
            <div><strong>{title}</strong><small>{desc}</small></div>
            <span>{done ? 'DONE' : active ? 'RUNNING' : 'QUEUED'}</span>
          </div>
        )
      })}
    </div>
  )
}
