import { useLive } from '../../state/SessionContext'

/** Says out loud that the GitHub connection and the task result are simulated.  Hidden once they are not. */
export function PreviewNotice() {
  if (useLive()) return null
  return <div className="preview-notice">Preview · GitHub connection and task results are simulated.</div>
}
