import { Fragment, useMemo, useState, type ReactElement } from 'react'
import { conversation } from '../../../lib/conversation'
import { fmt, kb, shortModel } from '../../../lib/format'
import type { Call, RunBundle, Tests } from '../../../lib/types'
import { MessageView } from './MessageView'

/**
 * Everything the run did, in one list: every model call and every connection the container opened, interleaved,
 * ending in the verifier's verdict.  Click any row for what it actually carried.
 *
 * On time: calls.jsonl and egress.jsonl are both stamped by the proxy inside the container, so they share a clock
 * and interleave honestly.  run.json is stamped by run.sh on the host, which is usually a different timezone — so
 * started/finished are drawn as anchors at the ends rather than sorted in among the rest, and the elapsed column
 * counts from the first thing the proxy saw.  Comparing the two clocks directly would invent a seven-hour gap.
 */
export function TimelineTab({ bundle, live = false }: { bundle: RunBundle; live?: boolean }) {
  const [show, setShow] = useState({ calls: true, net: true })
  const [open, setOpen] = useState<Set<string>>(new Set())

  const { events, folded } = useMemo(() => timeline(bundle), [bundle])
  const counts = useMemo(() => ({
    calls: events.filter(e => e.kind === 'call').length,
    net: events.filter(e => e.kind === 'net').length,
  }), [events])

  const visible = events.filter(e => (e.kind === 'call' ? show.calls : e.kind === 'net' ? show.net : true))
  const toggle = (id: string) => setOpen(prev => {
    const next = new Set(prev)
    next.has(id) ? next.delete(id) : next.add(id)
    return next
  })

  return (
    <>
      <div className="toolbar">
        <span>{counts.calls + counts.net} events</span>
        <label>
          <input type="checkbox" checked={show.calls}
                 onChange={e => setShow(s => ({ ...s, calls: e.target.checked }))} /> {counts.calls} model calls
        </label>
        <label>
          <input type="checkbox" checked={show.net}
                 onChange={e => setShow(s => ({ ...s, net: e.target.checked }))} /> {counts.net} connections
        </label>
        {folded > 0 && (
          <span className="muted" title={`egress.jsonl also logged ${folded} connections to hr-proxy-${bundle.run}, which are the model calls above`}>
            · {folded} proxy hops folded in
          </span>
        )}
        {live && <span className="tl-live">● following</span>}
      </div>

      {!counts.calls && !counts.net
        ? <div className="empty">nothing recorded yet{live ? ' — waiting for the first call.' : '.'}</div>
        : (
          <table className="tl">
            <tbody>
              {visible.map(event => (
                <Fragment key={event.id}>
                  {event.kind === 'mark'
                    ? <tr className="tl-mark"><td colSpan={4}>{event.clock} · {event.title}</td></tr>
                    : (
                      <tr className="row" onClick={() => toggle(event.id)} title={event.clock}>
                        <td className="num tl-at">{event.at}</td>
                        <td className="tl-tag"><span className={`pill ${event.tone || ''}`}>{event.tag}</span></td>
                        <td className="tl-what">{event.title}{event.note && <span className="muted small"> {event.note}</span>}</td>
                        <td className="num small muted tl-nums">{event.nums}</td>
                      </tr>
                    )}
                  {open.has(event.id) && event.detail && (
                    <tr className="detail"><td colSpan={4}>{event.detail()}</td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
    </>
  )
}

interface Event {
  id: string
  kind: 'call' | 'net' | 'tests' | 'mark'
  /** elapsed from the first proxy event, or '' for the anchors */
  at: string
  /** the raw stamp, shown on hover — whichever clock wrote it */
  clock: string
  tag: string
  tone?: 'ok' | 'bad' | 'warn'
  title: string
  note?: string
  nums?: string
  detail?: () => ReactElement
}

/** Wall-clock seconds between two stamps from the same clock.  NaN-safe: an unparseable stamp sorts as 0. */
const secs = (from: string, to: string) => {
  const a = Date.parse(from), b = Date.parse(to)
  return Number.isNaN(a) || Number.isNaN(b) ? 0 : (b - a) / 1000
}

const elapsed = (s: number) => {
  const whole = Math.max(0, Math.round(s))
  return `+${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`
}

const clock = (ts: string | null | undefined) => (ts || '').replace('T', ' ')

/** What the model did on this call: the tools it asked for, or the reply it ended with. */
function action(call: Call): { label: string; note?: string } {
  if (call.error) return { label: 'error', note: call.error }
  const final = conversation(call).find(t => t.final)
  const tools = final?.calls || []
  if (tools.length) return { label: tools.map(t => t.name).join(', '), note: tools.length > 1 ? `${tools.length} tools` : undefined }
  const text = (final?.text || '').trim()
  if (text) return { label: 'replied', note: text.slice(0, 80).replace(/\s+/g, ' ') }
  return { label: 'no content' }
}

/**
 * Every recorded event in one list: the proxy's own, sorted together, between the host's two anchors.
 *
 * The agent reaches the recording proxy through the egress proxy, so every model call is logged twice — once in
 * calls.jsonl and again in egress.jsonl as a connection to `hr-proxy-<run>` (lib/execute.sh names the container,
 * Docker lowercases it).  Those hops carry nothing the call row does not, so they are folded away and counted.
 */
function timeline(bundle: RunBundle): { events: Event[]; folded: number } {
  const calls = bundle.calls || []
  const ownProxy = `hr-proxy-${bundle.run}`.toLowerCase()
  const all = bundle.egress || []
  const egress = all.filter(e => (e.host || '').toLowerCase() !== ownProxy)
  const stamps = [...calls, ...egress].map(r => r.ts).filter((t): t is string => !!t).sort()
  const origin = stamps[0] || ''

  const from: Event[] = []

  calls.forEach((call, i) => {
    const { label, note } = action(call)
    from.push({
      id: `call-${i}`,
      kind: 'call',
      at: origin && call.ts ? elapsed(secs(origin, call.ts)) : '',
      clock: clock(call.ts),
      tag: `call ${call.n ?? i + 1}`,
      tone: call.error ? 'bad' : undefined,
      title: label,
      note,
      nums: [
        shortModel(call.model),
        call.latency_ms != null ? `${fmt(call.latency_ms)} ms` : '',
        `${fmt(call.usage?.input_tokens)} in / ${fmt(call.usage?.output_tokens)} out`,
      ].filter(Boolean).join('  ·  '),
      detail: () => <CallDetail call={call} />,
    })
  })

  egress.forEach((net, i) => {
    from.push({
      id: `net-${i}`,
      kind: 'net',
      at: origin && net.ts ? elapsed(secs(origin, net.ts)) : '',
      clock: clock(net.ts),
      tag: net.allowed === false ? 'blocked' : 'net',
      tone: net.allowed === false ? 'bad' : 'ok',
      title: `${net.host || '?'}${net.port && net.port !== 443 ? `:${net.port}` : ''}`,
      // The rule is often just the phase restated ("verify phase"); say it once.
      note: [net.method, net.phase && `${net.phase} phase`, net.rule !== `${net.phase} phase` ? net.rule : '']
        .filter(Boolean).join(' · '),
      nums: [
        net.status != null ? String(net.status) : '',
        net.bytes_up != null ? `↑${kb(net.bytes_up)}` : '',
        net.bytes_down != null ? `↓${kb(net.bytes_down)}` : '',
        net.ms != null ? `${fmt(net.ms)} ms` : '',
      ].filter(Boolean).join('  ·  '),
      detail: () => <pre>{JSON.stringify(net, null, 2)}</pre>,
    })
  })

  // The proxy's events share one clock, so this sort is the real order.  A missing stamp keeps its arrival order.
  from.sort((a, b) => (a.clock && b.clock ? a.clock.localeCompare(b.clock) : 0))

  const run = bundle.run_json
  const head: Event[] = [{
    id: 'start', kind: 'mark', at: '', clock: clock(run.started) || '—',
    tag: 'start', title: `started · ${run.harness?.name || 'harness'} · ${shortModel(run.model)}`,
  }]

  const tail: Event[] = []
  const tests = bundle.verifier?.tests
  if (tests) tail.push(testsEvent(tests, from.length))
  tail.push({
    id: 'finish', kind: 'mark', at: '', clock: clock(run.finished) || '—',
    tag: 'finish',
    title: run.finished
      ? `finished · rc ${run.rc ?? '—'} · ${fmt(run.seconds)}s${run.kind === 'harbor' ? ` · reward ${run.reward ?? '—'}` : ''}`
      : 'still running',
  })

  return { events: [...head, ...from, ...tail], folded: all.length - egress.length }
}

function testsEvent(tests: Tests, n: number): Event {
  const failed = tests.failed > 0
  return {
    id: `tests-${n}`,
    kind: 'tests',
    at: '',
    clock: 'verifier',
    tag: 'tests',
    tone: tests.aborted ? 'warn' : failed ? 'bad' : 'ok',
    title: tests.aborted
      ? `verifier aborted: ${tests.aborted}`
      : `${tests.passed} passed, ${tests.failed} failed of ${tests.total}`,
    note: tests.agent_written ? `${tests.agent_written} written by the agent` : undefined,
    nums: tests.summary || '',
    detail: () => <TestsDetail tests={tests} />,
  }
}

/** The call's own turn — what it asked for and what came back — with the raw payloads underneath. */
function CallDetail({ call }: { call: Call }) {
  const final = conversation(call).find(t => t.final)
  return (
    <>
      {final && <MessageView turn={final} />}
      <details><summary>request</summary><pre>{JSON.stringify(call.request, null, 2)}</pre></details>
      <details><summary>response</summary><pre>{JSON.stringify(call.response ?? call.error, null, 2)}</pre></details>
    </>
  )
}

/** Failures first, with the traceback the verifier printed; then the passes, named. */
function TestsDetail({ tests }: { tests: Tests }) {
  const cases = tests.cases || []
  if (!cases.length) return <div className="muted small">no per-test detail — the verifier did not print a pytest list.</div>
  const failures = cases.filter(c => c.result !== 'PASSED')
  const passes = cases.filter(c => c.result === 'PASSED')
  return (
    <>
      {failures.map((test, i) => (
        <div key={i} className="tl-case">
          <span className="pill bad">{test.result}</span> <span className="mono">{test.file} :: {test.name}</span>
          {test.detail && <pre className="err">{test.detail}</pre>}
        </div>
      ))}
      {!!passes.length && (
        <details>
          <summary>{passes.length} passed</summary>
          <pre>{passes.map(t => `${t.result.padEnd(7)} ${t.file} :: ${t.name}`).join('\n')}</pre>
        </details>
      )}
    </>
  )
}
