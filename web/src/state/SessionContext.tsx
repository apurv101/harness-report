import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { getSession } from '../lib/api'
import type { Session } from '../lib/types'

/**
 * Served by serve.py, /api/me answers and real GitHub sign-in takes over; on the static
 * Cloudflare Pages copy it 404s and the simulated preview stands.
 */
const SessionContext = createContext<Session | null>(null)
/** serve.py answered at all — so runs are real, whether or not GitHub sign-in is configured.  null until known. */
const ServedContext = createContext<boolean | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [served, setServed] = useState<boolean | null>(null)
  useEffect(() => {
    const ac = new AbortController()
    getSession(ac.signal).then(me => { setServed(true); if (me.auth) setSession(me) }).catch(() => { if (!ac.signal.aborted) setServed(false) /* static site: stay in preview */ })
    return () => ac.abort()
  }, [])
  return (
    <ServedContext.Provider value={served}>
      <SessionContext.Provider value={session}>{children}</SessionContext.Provider>
    </ServedContext.Provider>
  )
}

export const useSession = () => useContext(SessionContext)

/** True once real GitHub sign-in is configured and reachable — not the simulation. */
export const useLive = () => !!useSession()?.auth

/** True when serve.py is behind the page, so "Run task" starts run.sh instead of the simulation; null while asking. */
export const useServed = () => useContext(ServedContext)
