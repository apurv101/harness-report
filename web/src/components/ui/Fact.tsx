import type { ReactNode } from 'react'
import { HELP } from '../../lib/help'

/** A term with its definition on hover, where we have one. */
export function Label({ name }: { name: string }) {
  return HELP[name] ? <span className="help" title={HELP[name]}>{name}</span> : <>{name}</>
}

/** One label/value pair in a facts grid.  Empty values read as an em dash, not as nothing. */
export function Fact({ name, value }: { name: string; value: ReactNode }) {
  const empty = value == null || value === ''
  return (
    <div className="fact">
      <div className="k"><Label name={name} /></div>
      <div className="v">{empty ? '—' : value}</div>
    </div>
  )
}

export function Facts({ children }: { children: ReactNode }) {
  return <div className="facts">{children}</div>
}
