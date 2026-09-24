import { useState } from 'react'
import { conversation } from '../../../lib/conversation'
import { fmt } from '../../../lib/format'
import type { Call } from '../../../lib/types'
import { MessageView } from './MessageView'

/**
 * The trajectory, reconstructed from one call's request plus its response.  In an agent loop
 * every request carries the whole conversation so far, so the last call is the full run.
 */
export function TrajectoryTab({ calls }: { calls: Call[] }) {
  const [index, setIndex] = useState(calls.length - 1)
  const [showSystem, setShowSystem] = useState(true)

  if (!calls.length) return <div className="empty">no model calls were recorded (calls.jsonl is empty or missing).</div>

  const call = calls[Math.min(index, calls.length - 1)]
  const turns = conversation(call)

  return (
    <>
      <div className="toolbar">
        conversation as sent in call
        <select value={index} onChange={e => setIndex(Number(e.target.value))}>
          {calls.map((c, i) => (
            <option value={i} key={i}>{c.n ?? i + 1} of {calls.length}{c.error ? ' (error)' : ''}</option>
          ))}
        </select>
        <span>· {call.route} · {fmt(call.usage?.input_tokens)} in / {fmt(call.usage?.output_tokens)} out · {fmt(call.latency_ms)} ms</span>
        <label>
          <input type="checkbox" checked={showSystem} onChange={e => setShowSystem(e.target.checked)} /> system prompt
        </label>
      </div>
      <div>
        {turns.map((turn, i) => (
          (showSystem || turn.role !== 'system') && <MessageView turn={turn} key={i} />
        ))}
      </div>
    </>
  )
}
