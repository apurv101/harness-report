import { Fragment, useState } from 'react'
import { stopReason } from '../../../lib/conversation'
import { fmt, shortModel } from '../../../lib/format'
import { rawFileURL } from '../../../lib/api'
import { kb } from '../../../lib/format'
import type { Call, Trimmed } from '../../../lib/types'

/** Every request the proxy recorded, one row each; click a row for the raw request and response. */
export function CallsTab({ calls, run, trimmed = 0 }: { calls: Call[]; run?: string; trimmed?: number }) {
  const [open, setOpen] = useState<Set<number>>(new Set())

  if (!calls.length) return <div className="empty">no calls recorded.</div>

  const toggle = (i: number) => setOpen(prev => {
    const next = new Set(prev)
    next.has(i) ? next.delete(i) : next.add(i)
    return next
  })

  const cut = (t: Trimmed | undefined) => t && <p className="small muted">
    Left out here to fit the page: {t.fields.join(', ')} ({kb(t.bytes)} in all{t.messages != null ? `, ${t.messages} messages` : ''}).
    {run && <> <a href={rawFileURL(run, 'calls.jsonl')} target="_blank" rel="noopener">calls.jsonl</a> has the whole call.</>}
  </p>

  return (
    <>
    {trimmed > 0 && <p className="small muted" role="status">
      This run's calls are too big to send in full, so the big fields of {trimmed} earlier call{trimmed === 1 ? '' : 's'} (the
      conversation so far, the tool list) are left out below. The last call is complete, and the Trajectory is drawn from it.
      {run && <> The whole record: <a href={rawFileURL(run, 'calls.jsonl')} target="_blank" rel="noopener">calls.jsonl</a>.</>}
    </p>}
    <table>
      <thead>
        <tr>
          <th className="num">#</th><th>time</th><th>route</th><th>path</th><th>requested → used</th>
          <th>stream</th><th className="num">ms</th><th className="num">in</th><th className="num">out</th>
          <th>msgs</th><th>stop</th><th>error</th>
        </tr>
      </thead>
      <tbody>
        {calls.map((call, i) => (
          <Fragment key={i}>
            <tr className="row" onClick={() => toggle(i)}>
              <td className="num">{call.n ?? i + 1}</td>
              <td className="mono small">{(call.ts || '').replace('T', ' ')}</td>
              <td>{call.route}</td>
              <td className="mono small">{call.path}</td>
              <td className="mono small">{call.model_requested} → {shortModel(call.model)}</td>
              <td>{call.stream ? 'yes' : ''}</td>
              <td className="num">{fmt(call.latency_ms)}</td>
              <td className="num">{fmt(call.usage?.input_tokens)}</td>
              <td className="num">{fmt(call.usage?.output_tokens)}</td>
              <td className="num">{call.request_trimmed?.messages ?? (call.request?.messages || []).length}</td>
              <td className="mono small">{stopReason(call)}</td>
              <td className="err small">{call.error || ''}</td>
            </tr>
            {open.has(i) && (
              <tr className="detail">
                <td colSpan={12}>
                  <details open><summary>request</summary>{cut(call.request_trimmed)}<pre>{JSON.stringify(call.request, null, 2)}</pre></details>
                  <details open><summary>response</summary>{cut(call.response_trimmed)}<pre>{JSON.stringify(call.response ?? call.error, null, 2)}</pre></details>
                </td>
              </tr>
            )}
          </Fragment>
        ))}
      </tbody>
    </table>
    </>
  )
}
