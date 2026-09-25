import { useEffect, useState } from 'react'
import { getRun } from '../lib/api'
import type { RunBundle } from '../lib/types'

/** How often an unfinished run is asked for again. */
const EVERY_MS = 3000

/**
 * One run, followed while it is still going.  run.json gets its `finished` stamp only once run.sh is done, so an
 * absent one means the folder is still being written and the bundle is worth asking for again.  Unlike useJSON this
 * keeps the last good answer while the next one is in flight, so a growing timeline never blinks back to "Loading".
 *
 * The whole bundle comes back each time, calls and all — fine on localhost for the minute or two a run takes, and it
 * keeps the client honest about truncation and verifier state without a second endpoint to keep in step.
 */
export function useRunBundle(runId: string) {
  const [bundle, setBundle] = useState<RunBundle | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    setBundle(null)
    setError(null)
    if (!runId) return
    const ac = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined

    const poll = async () => {
      try {
        const next = await getRun(runId, ac.signal)
        setBundle(next)
        setError(null)
        if (!next.run_json.finished) timer = setTimeout(poll, EVERY_MS)
      } catch (e) {
        if (ac.signal.aborted) return
        // A run in flight can be mid-write, and serve.py may be restarting; keep the last good bundle on screen
        // and say so only when there was never one to show.
        setError(e instanceof Error && e.message ? e.message : 'This run could not be loaded.')
        timer = setTimeout(poll, EVERY_MS * 2)
      }
    }
    poll()
    return () => { ac.abort(); clearTimeout(timer) }
  }, [runId, attempt])

  return { bundle, error, live: !!bundle && !bundle.run_json.finished, reload: () => setAttempt(a => a + 1) }
}
