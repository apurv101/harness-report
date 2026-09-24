import type { ReactNode } from 'react'
import { useSession } from '../../state/SessionContext'
import { Icon } from '../ui/Icon'
import type { RepoOption } from '../../lib/types'

/** With no repository to show, point at the app installation that would grant one. */
function InstallOffer({ lead }: { lead: string }) {
  const installURL = useSession()?.install_url
  return (
    <p className="repo-empty" role="status">
      {lead}
      {installURL && <> <a className="text-link" href={installURL}>Install Harness Report on a repository <Icon name="arrow" /></a></>}
    </p>
  )
}

export function RepoEmpty({ children }: { children: ReactNode }) {
  return <p className="repo-empty" role="status">{children}</p>
}

export { InstallOffer }

/** The repositories on offer, filtered by the search box above them. */
export function RepoList({ repos, onSelect }: { repos: RepoOption[]; onSelect: (repo: string) => void }) {
  return (
    <>
      {repos.map(repo => (
        <button key={repo.name} className="repo-option" aria-label={`Import ${repo.name}`} onClick={() => onSelect(repo.name)}>
          <span className="repo-icon"><Icon name="repo" /></span>
          <span className="repo-info">
            <strong>{repo.name.split('/')[1]}</strong>
            <small>{repo.language} · {repo.description}</small>
          </span>
          <span className="repo-visibility">{repo.visibility}</span>
          <Icon name="arrow" />
        </button>
      ))}
    </>
  )
}
