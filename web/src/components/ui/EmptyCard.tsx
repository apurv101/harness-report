import type { ReactNode } from 'react'

/** The bordered "nothing here" card: no runs, no match, or a page that does not exist. */
export function EmptyCard({ children, role }: { children: ReactNode; role?: string }) {
  return <div className="empty-card" role={role}>{children}</div>
}
