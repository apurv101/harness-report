import { rawFileURL } from '../../../lib/api'
import { kb } from '../../../lib/format'
import type { RunBundle } from '../../../lib/types'

/** Everything the run folder holds, linked raw.  Non-core files came from the harness itself. */
export function FilesTab({ bundle }: { bundle: RunBundle }) {
  return (
    <>
      <table>
        <thead><tr><th>file</th><th className="num">size</th><th /></tr></thead>
        <tbody>
          {bundle.files.map(file => (
            <tr key={file.name}>
              <td className="mono">
                <a href={rawFileURL(bundle.run, file.name)} target="_blank" rel="noopener">{file.name}</a>
                {!file.core && <span className="muted small"> (written by the harness)</span>}
                {bundle.truncated?.includes(file.name) && <span className="muted small"> · stored head and tail only</span>}
              </td>
              <td className="num">{kb(file.bytes)}</td>
              <td className="small muted">{file.core ? '' : 'raw'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {bundle.files_omitted > 0 && (
        <p className="muted small">
          {bundle.files_omitted.toLocaleString()} more files are in the folder but not in the stored list — the
          harness wrote its own home directory into <code>/out</code>.
        </p>
      )}
      <p className="muted small">
        Folder: <code>runs/{bundle.run}/</code>
        {' · '}listed from {bundle.source === 'table' ? 'the run store (DynamoDB)' : 'the folder itself'}
      </p>
    </>
  )
}
