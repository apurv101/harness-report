import { useState } from 'react'
import { fmt } from '../../lib/format'

/**
 * Long text is clipped with a "show all" button.  Model output runs to megabytes; the page
 * stays scrollable only because most of it starts folded.
 */
export function Clipped({ text, limit, newline }: { text: string; limit: number; newline?: boolean }) {
  const [open, setOpen] = useState(false)
  const s = String(text)
  if (s.length <= limit) return <>{s}</>
  const hidden = s.length - limit
  return (
    <>
      {s.slice(0, limit)}
      {open && s.slice(limit)}
      {newline && '\n'}
      <button className="more" onClick={() => setOpen(o => !o)}>
        {open ? 'show less' : `… show ${fmt(hidden)} more chars`}
      </button>
    </>
  )
}
