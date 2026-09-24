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
              </td>
              <td className="num">{kb(file.bytes)}</td>
              <td className="small muted">{file.core ? '' : 'raw'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">Folder: <code>runs/{bundle.run}/</code></p>
    </>
  )
}
