import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getRunFiles, rawFileURL } from '../../lib/api'
import { kb } from '../../lib/format'
import type { RunFile } from '../../lib/types'

/**
 * What the run has written so far, each file linked as it appears: the task it was given, the command, the recipe
 * that built the sandbox, the proxy's recording of every model call, and the verifier's output once it runs.  The
 * list is polled from the folder the run is writing into; after the run it is the stored manifest.
 */
export function LiveArtifacts({ run, running }: { run: string; running: boolean }) {
  const [files, setFiles] = useState<RunFile[]>([])

  useEffect(() => {
    const ac = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    const poll = async () => {
      try { setFiles((await getRunFiles(run, ac.signal)).files) } catch { /* the run is what matters, not its index */ }
      if (running) timer = setTimeout(poll, 3000)
    }
    poll()
    return () => { ac.abort(); clearTimeout(timer) }
  }, [run, running])

  return (
    <details className="live-files" open={!running}>
      <summary>
        Written so far <span className="live-console-meta">{files.length ? `${files.length} files` : 'nothing yet'}</span>
      </summary>
      <ul>
        {files.map(f => (
          <li key={f.name}>
            <a href={rawFileURL(run, f.name)} target="_blank" rel="noopener">{f.name}</a>
            <span>{kb(f.bytes)}</span>
          </li>
        ))}
        {!files.length && <li className="muted">The run folder is created when the agent container starts.</li>}
      </ul>
      <p>
        <Link className="text-link" to={`/runs/${encodeURIComponent(run)}`}>Open the run</Link>
        {' · '}<code>runs/{run}/</code>
      </p>
    </details>
  )
}
