import { Pill, type Tone } from '../ui/Pill'
import type { Outcomes, RunRow } from '../../lib/types'

const TONE: Record<string, [string, Tone]> = {
  pass: ['Passed', 'ok'], fail: ['Failed', 'bad'], error: ['Error', 'bad'], running: ['Running', 'warn'],
}

/** One run's verdict, in the same words the runs list uses. */
export function OutcomePill({ outcome }: { outcome?: RunRow['outcome'] | null }) {
  const [text, tone] = TONE[outcome || ''] || ['—', 'plain']
  return <Pill tone={tone}>{text}</Pill>
}

/** Several runs of one harness on one task, folded: "2/3 passed", toned by the latest. */
export function OutcomesCell({ o }: { o: Outcomes }) {
  const tone: Tone = o.passes ? 'ok' : o.last_outcome === 'running' ? 'warn' : 'bad'
  return <Pill tone={tone} title={`last: ${o.last_outcome}`}>{o.passes}/{o.runs} passed</Pill>
}

/** A page's machine-readable twins, for anyone (or anything) that would rather read Markdown or JSON. */
export function Twins({ path }: { path: string }) {
  return (
    <p className="muted small twins">
      For agents: <a href={`${path}.md`}>{path}.md</a> · <a href={`${path}.json`}>.json</a> · <a href="/llms.txt">llms.txt</a>
    </p>
  )
}
