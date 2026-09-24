import type { EvalEvent, EvalLive, EvalState } from './types'

/** The bowling task the first real run uses: aider_polyglot / polyglot_python_bowling. */
export const BOWLING = {
  title: 'Bowling',
  summary: 'Score a game of bowling: frames, spares, strikes and the tenth-frame fill balls.',
  tests: 31,
  source: 'aider_polyglot · polyglot_python_bowling',
}

/** The four stages a real run shows, and which of run.sh's own stages belong to each. */
export const LIVE_STAGES = [
  ['Fetch repository', 'Clone your harness at its current commit.'],
  ['Prepare environment', 'Reuse or write the Docker setup, then build it for linux/amd64.'],
  ['Run bowling', 'Your agent works on the task; every model call goes through the recording proxy.'],
  ['Verify', `Run the task’s ${BOWLING.tests} tests against what the agent wrote.`],
] as const

function stageIndex(e: EvalEvent): number | null {
  switch (e.stage) {
    case 'fetch': case 'select': return 0
    case 'analyze': case 'build': return 1
    case 'proxy': return e.msg?.startsWith('recording') ? 2 : 1
    case 'task': case 'run': return 2
    case 'verify': return 3
    case 'summary': return 4
    default: return null
  }
}

export interface Progress {
  /** stages before this index are done; LIVE_STAGES.length when all are */
  completed: number
  /** one line under each stage, once there is something true to say */
  details: (string | null)[]
  error: string | null
}

const short = (sha?: string) => (sha || '').slice(0, 7)
const tokens = (n: number) => n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : String(n)

export function progress(events: EvalEvent[], live: EvalLive | null, state: EvalState | null): Progress {
  let completed = 0; let error: string | null = null
  const details: (string | null)[] = [null, null, null, null]
  let setup = ''
  for (const e of events) {
    const i = e.type === 'stage' ? stageIndex(e) : null
    if (i !== null) completed = Math.max(completed, i)
    if (e.type === 'fetched') details[0] = `At commit ${short(e.commit)}.`
    if (e.type === 'recipe') {
      if (e.mode === 'reused') setup = 'Docker setup reused for this commit, no AI call.'
      if (e.mode === 'analyzed') setup = e.seeded_from && e.seeded_from !== 'none'
        ? `Docker setup written by AI, starting from the one for ${short(e.seeded_from)}.`
        : 'Docker setup written by AI.'
      if (e.mode === 'failed') setup = `Docker setup attempt ${e.attempt} failed; trying again.`
    }
    if (e.type === 'built') setup = `${setup} Built for ${e.platform}.`.trim()
    if (e.type === 'error') error = e.msg || 'the run stopped'
  }
  details[1] = setup || null
  if (live && (live.calls || completed >= 2)) {
    details[2] = `${live.calls} model call${live.calls === 1 ? '' : 's'} · ${tokens(live.input_tokens + live.output_tokens)} tokens`
      + (live.errors ? ` · ${live.errors} rejected` : '') + (live.last_action ? `\nLast: ${live.last_action}` : '')
  }
  const t = state?.result?.tests
  if (t && t.total) details[3] = `${t.passed} of ${t.total} tests passed.`
  if (state?.eval.status === 'done') completed = LIVE_STAGES.length
  if (state?.eval.status === 'failed') error = error || state.eval.error || 'the run stopped'
  return { completed, details, error }
}
