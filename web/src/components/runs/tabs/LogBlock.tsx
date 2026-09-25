import { rawFileURL } from '../../../lib/api'
import { byteSize, kb } from '../../../lib/format'

/**
 * One captured log file, with its size where there is one and a clear word where there is not.  A log stored in
 * DynamoDB keeps its head and its tail when the whole thing would not fit in one item; then this says so and links
 * the file itself, so nobody reads a gap as the end of the run.
 */
export function LogBlock({ title, text, run, cut = false }: {
  title: string
  text: string | null | undefined
  run?: string
  cut?: boolean
}) {
  return (
    <>
      <h2>
        {title} <span className="muted" style={{ textTransform: 'none', letterSpacing: 0 }}>
          {text == null ? '(missing)' : kb(byteSize(text))}
          {cut && <> · preview only</>}
          {run && text != null && <> · <a href={rawFileURL(run, title)} target="_blank" rel="noopener">Open log file</a></>}
        </span>
      </h2>
      {text ? <pre>{text}</pre> : <div className="muted small">empty</div>}
    </>
  )
}
