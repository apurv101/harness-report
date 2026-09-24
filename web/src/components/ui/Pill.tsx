import type { ReactNode } from 'react'

export type Tone = 'ok' | 'bad' | 'warn' | 'plain'

/** The one status chip the run viewer uses everywhere: green pass, red fail, amber unknown. */
export function Pill({ tone = 'plain', title, children }: { tone?: Tone; title?: string; children: ReactNode }) {
  return <span className={tone === 'plain' ? 'pill' : `pill ${tone}`} title={title}>{children}</span>
}
