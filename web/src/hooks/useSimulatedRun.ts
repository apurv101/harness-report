import { useEffect, useState } from 'react'
import { STAGES } from '../lib/preview'

/**
 * The preview's FizzBuzz run: four stages, then the example report.  Nothing executes —
 * the timers are the whole simulation.
 */
export function useSimulatedRun(running: boolean, onDone: () => void) {
  const [completed, setCompleted] = useState(0)

  useEffect(() => {
    if (!running) { setCompleted(0); return }
    const timers = STAGES.map((_, i) => setTimeout(() => setCompleted(i + 1), (i + 1) * 1300))
    timers.push(setTimeout(onDone, STAGES.length * 1300 + 550))
    return () => timers.forEach(clearTimeout)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running])

  const announcement = completed === 0
    ? 'Preview: fetching the repository…'
    : completed < STAGES.length
      ? `Preview: ${STAGES[completed][0].toLowerCase()}…`
      : 'Preview check complete. Opening the example report…'

  return { completed, announcement }
}
