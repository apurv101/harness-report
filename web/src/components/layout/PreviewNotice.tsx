import { useLive, useServed } from '../../state/SessionContext'

/**
 * Says out loud what is simulated.  On the static site: the GitHub connection and the task result.  With serve.py
 * but no GitHub sign-in configured: only the connection — runs are real.  Hidden once nothing is.
 */
export function PreviewNotice() {
  const live = useLive(); const served = useServed()
  if (live || served === null) return null      // null: still asking serve.py
  return <div className="preview-notice">
    {served ? 'Preview · GitHub connection is simulated. Runs are real, on this machine.' : 'Preview · GitHub connection and task results are simulated.'}
  </div>
}
