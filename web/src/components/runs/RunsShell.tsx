import type { ReactNode } from 'react'

/** The frame both run views share: the breadcrumb, then whatever loaded. */
export function RunsShell({ crumb, children }: { crumb: ReactNode; children: ReactNode }) {
  return (
    <section className="runs-view">
      <nav className="crumb" aria-label="Breadcrumb">{crumb}</nav>
      <div>{children}</div>
    </section>
  )
}
