import { useNavigate } from 'react-router-dom'
import { FlowHeading, FlowLayout } from '../components/onboarding/FlowLayout'
import { Icon } from '../components/ui/Icon'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { usePreview } from '../state/PreviewContext'
import { useLive } from '../state/SessionContext'

/** Step 1.  With a GitHub App configured this leaves for GitHub; without one it just pretends. */
export function SignInPage() {
  useDocumentTitle('Connect with GitHub · Harness Report')
  const live = useLive()
  const { connect } = usePreview()
  const navigate = useNavigate()

  const signIn = () => {
    if (live) { window.location.href = '/auth/github'; return }
    connect()
    navigate('/import')
  }

  return (
    <FlowLayout step={1}>
      <FlowHeading step={1} title="Sign in with GitHub." text="Your code is the starting point." />
      <div className="flow-card signin-card">
        <div className="signin-mark"><Icon name="github" /></div>
        <button className="ui-btn primary wide" onClick={signIn}>
          <Icon name="github" /> Continue with GitHub <Icon name="arrow" />
        </button>
        <p className="signin-meta">
          {live ? 'You will be sent to GitHub to authorise Harness Report.' : 'Sample workspace · No account required for this preview.'}
        </p>
      </div>
    </FlowLayout>
  )
}
