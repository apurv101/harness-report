import { Link, useLocation } from 'react-router-dom'
import { usePreview } from '../../state/PreviewContext'
import { Wordmark } from './Wordmark'
import { useSession } from '../../state/SessionContext'

/** One header for every view: the mark, the harness / task / run indexes, and where sign-in currently stands. */
export function SiteHeader() {
  const { pathname } = useLocation()
  const { signedIn } = usePreview()
  const queued = ['local-queue', 'queue'].includes(useSession()?.eval_mode || '')
  const on = (root: string) => (pathname === root || pathname.startsWith(`${root}/`) ? 'page' : undefined)
  return (
    <header className="top">
      <div className="wrap">
        <Wordmark />
        <div className="header-actions">
          <Link className="header-signin" to="/harnesses" aria-current={on('/harnesses')}>Harnesses</Link>
          <Link className="header-signin" to="/tasks" aria-current={on('/tasks')}>Tasks</Link>
          <Link className="header-signin" to="/runs" aria-current={on('/runs')}>Runs</Link>
          {queued && signedIn && <Link className="header-signin" to="/evaluations" aria-current={on('/evaluations')}>Your evaluations</Link>}
          <Link className="header-signin" to={signedIn ? '/import' : '/connect'}>{signedIn ? 'Your harness' : 'Sign in'}</Link>
          <Link className="ui-btn primary small" to="/connect">Get started <span aria-hidden="true">↗</span></Link>
        </div>
      </div>
    </header>
  )
}
