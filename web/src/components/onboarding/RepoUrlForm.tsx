import { useRef, useState } from 'react'
import { parseRepoURL } from '../../lib/github'
import { Icon } from '../ui/Icon'

/** The escape hatch from the list: paste any GitHub URL. */
export function RepoUrlForm({ onSelect }: { onSelect: (repo: string) => void }) {
  const [value, setValue] = useState('')
  const [error, setError] = useState('')
  const input = useRef<HTMLInputElement>(null)

  return (
    <>
      <div className="import-divider">or import by URL</div>
      <form className="repo-form" noValidate onSubmit={event => {
        event.preventDefault()
        const repo = parseRepoURL(value)
        if (!repo) {
          setError('Enter a GitHub repository URL, like https://github.com/owner/repository.')
          input.current?.focus()
          return
        }
        onSelect(repo)
      }}>
        <label htmlFor="repo-url">GitHub repository URL</label>
        <div className="repo-input-row">
          <input id="repo-url" ref={input} type="url" value={value} autoComplete="off"
                 placeholder="https://github.com/your-workspace/my-agent"
                 aria-invalid={error ? true : undefined} aria-describedby="repo-url-error"
                 onChange={e => { setValue(e.target.value); setError('') }} />
          <button className="ui-btn" type="submit">Import <Icon name="arrow" /></button>
        </div>
        <p id="repo-url-error" className="field-error" role="alert" hidden={!error}>{error}</p>
      </form>
    </>
  )
}
