import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { readPreview, writePreview, type PreviewState } from '../lib/preview'
import { useSession } from './SessionContext'

/** The onboarding flow's own state: sign-in (real or simulated), chosen repository, first-task result. */
interface PreviewValue extends PreviewState {
  /** Signed in for real, or simulated far enough to continue the flow. */
  signedIn: boolean
  connect: () => void
  selectRepo: (repo: string, meta?: PreviewState['repoMeta']) => void
  setResult: (result: PreviewState['result']) => void
  setEval: (evalId: string | null) => void
}

const PreviewContext = createContext<PreviewValue | null>(null)

export function PreviewProvider({ children }: { children: ReactNode }) {
  const session = useSession()
  const [state, setState] = useState<PreviewState>(readPreview)

  const update = useCallback((next: PreviewState) => {
    setState(prev => {
      const merged = { ...prev, ...next }
      writePreview(merged)
      return merged
    })
  }, [])

  const value = useMemo<PreviewValue>(() => ({
    ...state,
    signedIn: session?.auth ? !!session.user : !!state.connected,
    connect: () => update({ connected: true }),
    selectRepo: (repo: string, meta?: PreviewState['repoMeta']) => update({ repo, repoMeta: meta ?? null, result: null, evalId: null }),
    setResult: (result: PreviewState['result']) => update({ result }),
    setEval: (evalId: string | null) => update({ evalId }),
  }), [state, session, update])

  return <PreviewContext.Provider value={value}>{children}</PreviewContext.Provider>
}

export function usePreview(): PreviewValue {
  const value = useContext(PreviewContext)
  if (!value) throw new Error('usePreview outside PreviewProvider')
  return value
}
