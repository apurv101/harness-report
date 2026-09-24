import { Icon } from '../ui/Icon'

/** Illustrative only: what a finished evaluation looks like, before you have run one. */
const TASKS = [
  ['Fix a bug', true],
  ['Write tests', true],
  ['Update an API', false],
  ['Build a feature', true],
] as const

export function ExampleReport() {
  return (
    <div className="preview-window" role="img"
         aria-label="Example evaluation report, showing three of four tasks passed. Illustrative results only.">
      <div className="window-chrome"><i /><i /><i /><span>EXAMPLE REPORT</span></div>
      <div className="preview-body">
        <div className="preview-repo"><span className="repo-icon"><Icon name="repo" /></span> your-workspace / my-agent</div>
        <div className="evaluation-score"><strong>3<span> / 4</span></strong><span>Tasks passed</span></div>
        {TASKS.map(([name, passed]) => (
          <div className="evaluation-row" key={name}>
            <span>{name}</span>
            {passed
              ? <span className="pass-label"><Icon name="check" /> Passed</span>
              : <span className="fail-label">Needs work</span>}
          </div>
        ))}
        <div className="evaluation-footer">Results, model calls, and every step in between.</div>
      </div>
    </div>
  )
}
