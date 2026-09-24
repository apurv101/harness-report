import { useEffect, useState } from 'react'

export interface Loaded<T> {
  data: T | null
  error: string | null
  /** Bumped by retry() to run the fetch again. */
  reload: () => void
}

/**
 * One aborted-on-unmount fetch.  `load` must take the signal and pass it on, so navigating
 * away mid-request never lands a stale result on the next page.
 */
export function useJSON<T>(load: (signal: AbortSignal) => Promise<T>, deps: unknown[], message: string): Loaded<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const ac = new AbortController()
    setData(null)
    setError(null)
    load(ac.signal)
      .then(setData)
      .catch((e: Error) => { if (e.name !== 'AbortError') setError(message) })
    return () => ac.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, attempt])

  return { data, error, reload: () => setAttempt(a => a + 1) }
}
