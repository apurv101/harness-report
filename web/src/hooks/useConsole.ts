import { useEffect, useState } from 'react'
import { getEvalConsole } from '../lib/api'

/**
 * Follow run.sh's own terminal output for one evaluation: poll from a byte cursor every 1.2 s and append whatever
 * has been written, until the run is no longer running (the last answer carries the tail).  This is the only place
 * the fetch, the analyzer's turns and the docker build are visible — the events are stage banners, not output.
 */
export function useConsole(id: string | null | undefined) {
  const [text, setText] = useState('')
  const [bytes, setBytes] = useState(0)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setText(''); setBytes(0); setError(null)
    if (!id) return
    const ac = new AbortController()
    let next = 0; let timer: ReturnType<typeof setTimeout> | undefined
    const poll = async () => {
      try {
        const c = await getEvalConsole(id, next, ac.signal)
        next = c.next
        if (c.text) setText(prev => prev + c.text)
        setBytes(c.bytes); setError(null)
        if (c.status === 'running') timer = setTimeout(poll, 1200)
      } catch (e) {
        if (ac.signal.aborted) return
        setError(e instanceof Error ? e.message : String(e))
        timer = setTimeout(poll, 4000)      // serve.py restarting: the run goes on writing without it
      }
    }
    poll()
    return () => { ac.abort(); clearTimeout(timer) }
  }, [id])

  return { text, bytes, error }
}
