import { byteSize, kb } from '../../../lib/format'

/** One captured log file, with its size where there is one and a clear word where there is not. */
export function LogBlock({ title, text }: { title: string; text: string | null | undefined }) {
  return (
    <>
      <h2>
        {title} <span className="muted" style={{ textTransform: 'none', letterSpacing: 0 }}>
          {text == null ? '(missing)' : kb(byteSize(text))}
        </span>
      </h2>
      {text ? <pre>{text}</pre> : <div className="muted small">empty</div>}
    </>
  )
}
