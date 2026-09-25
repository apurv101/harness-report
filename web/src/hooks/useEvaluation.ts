import { useEffect, useState } from 'react'
import { getEval } from '../lib/api'
import { inProgress } from '../lib/evaluation'
import type { EvalEvent, EvalState } from '../lib/types'

/**
 * Follow one evaluation: poll serve.py with an event cursor every 1.5 s while it runs, keep every event,
 * and stop once it has finished (queued and running are both still going) (the last answer carries the result).
 */
export function useEvaluation(id: string | null | undefined) {
  const [state, setState] = useState<EvalState | null>(null)
  const [events, setEvents] = useState<EvalEvent[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setState(null); setEvents([]); setError(null)
    if (!id) return
    const ac = new AbortController()
    let next = 0; let timer: ReturnType<typeof setTimeout> | undefined
    const poll = async () => {
      try {
        const s = await getEval(id, next, ac.signal)
        next = s.next
        if (s.events.length) setEvents(prev => [...prev, ...s.events])
        setState(s); setError(null)
        if (inProgress(s.eval.status)) timer = setTimeout(poll, 1500)
      } catch (e) {
        if (ac.signal.aborted) return
        setError(e instanceof Error ? e.message : String(e))
        timer = setTimeout(poll, 4000)     // serve.py restarting: keep trying, the run goes on without it
      }
    }
    poll()
    return () => { ac.abort(); clearTimeout(timer) }
  }, [id])

  return { state, events, error }
}
