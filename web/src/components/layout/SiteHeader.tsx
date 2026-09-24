import { Link, useLocation } from 'react-router-dom'
import { usePreview } from '../../state/PreviewContext'
import { Wordmark } from './Wordmark'

/** One header for every view: the mark, the runs link, and where sign-in currently stands. */
export function SiteHeader() {
  const { pathname } = useLocation()
  const { signedIn } = usePreview()
  const onRuns = pathname === '/runs' || pathname.startsWith('/runs/')
  return (
    <header className="top">
      <div className="wrap">
        <Wordmark />
        <div className="header-actions">
          <Link className="header-signin" to="/runs" aria-current={onRuns ? 'page' : undefined}>Runs</Link>
          <Link className="header-signin" to={signedIn ? '/import' : '/connect'}>{signedIn ? 'Your harness' : 'Sign in'}</Link>
          <Link className="ui-btn primary small" to="/connect">Get started <span aria-hidden="true">↗</span></Link>
        </div>
      </div>
    </header>
  )
}
