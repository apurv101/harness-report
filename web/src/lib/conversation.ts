import type { Call, ContentBlock, RequestMessage } from './types'

/** One turn of the reconstructed conversation, normalised across both API shapes. */
export interface Turn {
  role: string
  text?: string
  calls?: ToolCall[]
  results?: ToolResult[]
  final?: boolean
  error?: string
}

export interface ToolCall {
  name: string
  pretty: string
}

export interface ToolResult {
  id?: string
  text: string
  is_error?: boolean
}

/** Content can be a string, a list of blocks, or something unexpected; make it readable either way. */
function text(v: unknown): string {
  if (typeof v === 'string') return v
  if (Array.isArray(v)) {
    return v
      .map(p => {
        if (typeof p === 'string') return p
        const block = p as ContentBlock
        if (block?.type === 'text') return block.text ?? ''
        if (block?.type === 'image_url' || block?.type === 'image') return '[image]'
        return JSON.stringify(p)
      })
      .join('\n')
  }
  return v == null ? '' : JSON.stringify(v)
}

export function toolCall(name: string | undefined, args: unknown): ToolCall {
  let a = args
  let pretty: string | null = null
  if (typeof args === 'string') {
    try { a = JSON.parse(args) } catch { pretty = args }
  }
  if (pretty == null && a && typeof a === 'object') {
    const obj = a as Record<string, unknown>
    const keys = Object.keys(obj)
    const main = obj.command ?? obj.cmd ?? obj.code ?? obj.script ?? null
    pretty = keys.length === 1 && typeof main === 'string' ? main : JSON.stringify(obj, null, 2)
  }
  return { name: name || 'tool', pretty: pretty ?? String(args ?? '') }
}

/** Anthropic messages carry content blocks; fold them into one turn. */
function blocks(m: { role: string; content?: unknown }): Turn {
  const list: ContentBlock[] = Array.isArray(m.content)
    ? (m.content as ContentBlock[])
    : [{ type: 'text', text: text(m.content) }]
  const turn: Turn = { role: m.role, text: '', calls: [], results: [] }
  const add = (s: string) => { turn.text = (turn.text ? `${turn.text}\n` : '') + s }
  for (const bl of list) {
    if (bl.type === 'text') add(bl.text ?? '')
    else if (bl.type === 'tool_use') turn.calls!.push(toolCall(bl.name, bl.input))
    else if (bl.type === 'tool_result') turn.results!.push({ id: bl.tool_use_id, text: text(bl.content), is_error: bl.is_error })
    else if (bl.type === 'thinking') add(`[thinking] ${bl.thinking || ''}`)
    else add(JSON.stringify(bl))
  }
  if (m.role === 'user' && turn.results!.length && !turn.text) turn.role = 'tool'
  return turn
}

/**
 * The whole conversation as one call carried it.  In an agent loop every request resends the
 * conversation so far, so the last call holds the full trajectory.
 */
export function conversation(c: Call): Turn[] {
  const req = c.request || {}
  const out: Turn[] = []
  if (c.route === 'openai') {
    for (const m of (req.messages || []) as RequestMessage[]) {
      if (m.role === 'system' || m.role === 'developer') out.push({ role: 'system', text: text(m.content) })
      else if (m.role === 'user') out.push({ role: 'user', text: text(m.content) })
      else if (m.role === 'assistant')
        out.push({ role: 'assistant', text: text(m.content), calls: (m.tool_calls || []).map(tc => toolCall(tc.function?.name, tc.function?.arguments)) })
      else if (m.role === 'tool') out.push({ role: 'tool', results: [{ id: m.tool_call_id, text: text(m.content) }] })
      else out.push({ role: m.role, text: text(m.content) })
    }
    const rm = c.response?.choices?.[0]?.message
    if (rm)
      out.push({ role: 'assistant', final: true, text: text(rm.content), calls: (rm.tool_calls || []).map(tc => toolCall(tc.function?.name, tc.function?.arguments)) })
  } else {
    if (req.system) out.push({ role: 'system', text: text(req.system) })
    for (const m of (req.messages || []) as RequestMessage[]) out.push(blocks(m))
    if (c.response?.content) out.push({ ...blocks({ role: 'assistant', content: c.response.content }), final: true })
  }
  if (c.error) out.push({ role: 'assistant', final: true, error: c.error })
  return out
}

/**
 * Tool results are often JSON like {"returncode":0,"output":"…"}; show the output as text
 * with everything else as a one-line head.
 */
export function observation(t: string): { head: string; text: string } {
  try {
    const o = JSON.parse(t) as Record<string, unknown>
    if (o && typeof o === 'object' && !Array.isArray(o)) {
      const k = ['output', 'stdout', 'result', 'content', 'text'].find(k => typeof o[k] === 'string')
      if (k) {
        const head = Object.entries(o)
          .filter(([x]) => x !== k)
          .map(([x, v]) => `${x}=${typeof v === 'string' ? v : JSON.stringify(v)}`)
          .join('  ')
        return { head, text: o[k] as string }
      }
    }
  } catch { /* not JSON: show it as it came */ }
  return { head: '', text: t }
}

/** The finish reason, whichever API shape reported it. */
export const stopReason = (c: Call) => c.response?.choices?.[0]?.finish_reason ?? c.response?.stop_reason ?? ''
