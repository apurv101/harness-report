import { useEffect, useState } from 'react'
import { getRecs, startEval } from '../../lib/api'
import type { Rec, Recs } from '../../lib/types'
import { RecList } from './RecList'

const WAIT_MS = 150_000     // a first profile (claude -p reading the repo) takes about a minute

/**
 * After a run: the tests this harness should run next, for what it is for.  The runner re-ranks them once the
 * run settles, so this polls until the ranking says it has seen `afterRun`, then stops — or gives up and shows
 * whatever ranking there is.
 */
export function NextTests({ harness, repo, afterRun, onStarted }: {
  harness: string
  repo: string
  afterRun: string
  onStarted: (evalId: string) => void
}) {
  const [recs, setRecs] = useState<Recs | null>(null)
  const [waiting, setWaiting] = useState(true)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  useEffect(() => {
    const ac = new AbortController()
    const t0 = Date.now(); let timer: ReturnType<typeof setTimeout> | undefined
    const poll = async () => {
      try {
        const r = await getRecs(harness, ac.signal)
        if (r) setRecs(r)
        if (r?.based_on_run === afterRun || Date.now() - t0 > WAIT_MS) { setWaiting(false); return }
      } catch { if (ac.signal.aborted) return }
      timer = setTimeout(poll, 5000)
    }
    poll()
    return () => { ac.abort(); clearTimeout(timer) }
  }, [harness, afterRun])

  const run = async (rec: Rec) => {
    setBusy(true); setProblem(null)
    try { const s = await startEval(repo, rec); onStarted(s.eval.id) }
    catch (e) { setProblem(e instanceof Error ? e.message : String(e)); setBusy(false) }
  }

  return (
    <section className="flow-card next-tests" aria-busy={waiting}>
      <div className="check-card-header">
        <div>
          <h3>Next tests for your harness</h3>
          <p>{waiting && recs?.based_on_run !== afterRun
            ? 'Reading your harness and this result to pick what to run next…'
            : recs?.source === 'llm' ? 'Picked by a model from what your harness is for and how it did.'
            : 'Picked from what your harness is for and how it did.'}</p>
        </div>
      </div>
      <div className="check-card-body">
        {recs?.recs?.length ? <RecList recs={recs.recs} onRun={run} busy={busy} /> : waiting ? null : <p className="muted">No recommendations yet.</p>}
        {problem && <p className="flow-helper" role="alert">{problem}</p>}
      </div>
    </section>
  )
}
