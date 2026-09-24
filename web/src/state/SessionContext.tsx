import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { getSession } from '../lib/api'
import type { Session } from '../lib/types'

/**
 * Served by serve.py, /api/me answers and real GitHub sign-in takes over; on the static
 * Cloudflare Pages copy it 404s and the simulated preview stands.
 */
const SessionContext = createContext<Session | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  useEffect(() => {
    const ac = new AbortController()
    getSession(ac.signal).then(me => { if (me.auth) setSession(me) }).catch(() => { /* static site: stay in preview */ })
    return () => ac.abort()
  }, [])
  return <SessionContext.Provider value={session}>{children}</SessionContext.Provider>
}

export const useSession = () => useContext(SessionContext)

/** True once real GitHub sign-in is configured and reachable — not the simulation. */
export const useLive = () => !!useSession()?.auth
