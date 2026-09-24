import { Link } from 'react-router-dom'
import { useSession } from '../../state/SessionContext'
import { Icon } from '../ui/Icon'

/** Who the picker is listing repositories for: a real GitHub account, or the sample one. */
export function AccountBar() {
  const session = useSession()
  const user = session?.user
  return (
    <div className="account-bar">
      <span className="avatar">
        {user?.avatar ? <img src={user.avatar} alt="" width={26} height={26} /> : <Icon name="github" />}
      </span>
      <span className="account-name">
        {user ? user.login : 'your-workspace'} <span>{user ? 'GitHub account' : 'Sample GitHub account'}</span>
      </span>
      {user
        ? <a className="text-link" href="/auth/logout">Sign out</a>
        : <Link className="text-link" to="/connect">Switch account</Link>}
    </div>
  )
}
