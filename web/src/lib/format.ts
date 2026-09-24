import type { RunSummary } from './types'

export const fmt = (n: number | null | undefined) => (n == null ? '—' : Number(n).toLocaleString())

export const kb = (b: number) =>
  b < 1024 ? `${b} B` : b < 1048576 ? `${(b / 1024).toFixed(1)} KB` : `${(b / 1048576).toFixed(2)} MB`

export const byteSize = (s: string) => new Blob([s]).size

/** `bedrock/us.anthropic.claude-…` is mostly routing; show the model. */
export const shortModel = (m: string | undefined) =>
  (m || '').replace(/^bedrock\//, '').replace(/^us\.anthropic\./, '')

/** What the run was asked to do: a Harbor task path, or the prompt it was given. */
export const taskText = (r: RunSummary) =>
  r.kind === 'harbor' ? `${r.task?.taskset || ''} / ${r.task?.name || ''}` : r.prompt || ''

export const truncate = (s: string, n: number) => (s.length > n ? `${s.slice(0, n)}…` : s)
