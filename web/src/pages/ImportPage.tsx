import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AccountBar } from '../components/onboarding/AccountBar'
import { FlowHeading, FlowLayout } from '../components/onboarding/FlowLayout'
import { InstallOffer, RepoEmpty, RepoList } from '../components/onboarding/RepoList'
import { RepoUrlForm } from '../components/onboarding/RepoUrlForm'
import { Icon } from '../components/ui/Icon'
import { SearchInput } from '../components/ui/SearchInput'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { useJSON } from '../hooks/useJSON'
import { getUserRepos } from '../lib/api'
import { SAMPLE_REPOS } from '../lib/preview'
import type { RepoOption } from '../lib/types'
import { usePreview } from '../state/PreviewContext'
import { useLive, useSession } from '../state/SessionContext'

/** Step 2.  Signed in for real, these are the repositories the app installation grants. */
export function ImportPage() {
  useDocumentTitle('Import a harness · Harness Report')
  const live = useLive()
  const local = useSession()?.local_users
  const { selectRepo } = usePreview()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')

  const { data, error } = useJSON<RepoOption[]>(
    signal => (live ? getUserRepos(signal) : Promise.resolve([...SAMPLE_REPOS])),
    [live], 'github')

  // The repo's language and description travel with it: they are what the first task is picked from.
  const choose = (repo: string) => {
    const r = (data || []).find(x => x.name === repo)
    selectRepo(repo, r ? { language: r.language, description: r.description } : null)
    navigate('/check')
  }
  const matches = (data || []).filter(r => r.name.toLowerCase().includes(query.toLowerCase().trim()))

  return (
    <FlowLayout step={2}>
      <FlowHeading step={2} title="Choose your harness." text="Select a repository or paste its GitHub URL." />
      <div className="flow-card">
        <AccountBar />
        <SearchInput value={query} onChange={setQuery} icon
                     label="Find a repository" placeholder="Find a repository…" />
        <div className="repo-list">
          {error ? <InstallOffer lead="Could not reach GitHub. Paste a repository URL below, or try again:" />
           : !data ? <RepoEmpty>Loading your repositories…</RepoEmpty>
           : !data.length ? local ? <RepoEmpty>Paste a public GitHub repository URL below.</RepoEmpty> : <InstallOffer lead="Paste a public repository URL below — or, for a private one:" />
           : matches.length ? <RepoList repos={matches} onSelect={choose} />
           : live ? <InstallOffer lead={`No repository matches “${query.trim()}”. Paste its URL below, or:`} />
           : <RepoEmpty>No repositories found. Try another name or paste a GitHub URL below.</RepoEmpty>}
        </div>
        <RepoUrlForm onSelect={choose} />
      </div>
      <p className="flow-bottom-note">
        <Icon name="lock" /> {local ? 'Local test users can evaluate public repositories' : live ? 'Only the repositories you install Harness Report on' : 'Sample repositories · Preview only'}
      </p>
    </FlowLayout>
  )
}
