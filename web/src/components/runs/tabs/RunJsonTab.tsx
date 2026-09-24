import type { RunSummary } from '../../../lib/types'

export function RunJsonTab({ run }: { run: RunSummary }) {
  return (
    <>
      <h2>
        run.json <span className="muted" style={{ textTransform: 'none', letterSpacing: 0 }}>
          origin written before the run, result merged in after
        </span>
      </h2>
      <pre>{JSON.stringify(run, null, 2)}</pre>
    </>
  )
}
