import { useEffect, useRef } from 'react'
import { useConsole } from '../../hooks/useConsole'
import { evalConsoleURL } from '../../lib/api'
import { kb } from '../../lib/format'

/** How much of a long log is kept in the DOM.  The whole thing is one click away. */
const RENDER = 200_000

/**
 * run.sh's terminal output, live.  Everything the pipeline prints — the clone, the analyzer, the docker build, the
 * agent's own stdout — goes to evals/<id>/console.log, and until now nothing showed it: the stage list above says
 * which stage is running, this says what it is doing.  It follows the tail unless you scroll up to read.
 */
export function LiveConsole({ id }: { id: string }) {
  const { text, bytes, error } = useConsole(id)
  const box = useRef<HTMLPreElement>(null)
  const follow = useRef(true)

  useEffect(() => {
    const el = box.current
    if (el && follow.current) el.scrollTop = el.scrollHeight
  }, [text])

  const onScroll = () => {
    const el = box.current
    if (el) follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
  }

  return (
    <details className="live-console" open>
      <summary>
        Console <span className="live-console-meta">{error ? 'reconnecting…' : kb(bytes)}</span>
      </summary>
      <pre ref={box} onScroll={onScroll} aria-label="run.sh output" tabIndex={0}>
        {text.length > RENDER ? `…[${kb(bytes - RENDER)} earlier, in the full log]\n\n${text.slice(-RENDER)}` : text || 'Waiting for the first line…'}
      </pre>
      <a className="text-link" href={evalConsoleURL(id)} target="_blank" rel="noopener">Open the whole log</a>
    </details>
  )
}
