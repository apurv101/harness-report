import type { ReactElement } from 'react'
import { Navigate } from 'react-router-dom'
import { usePreview } from '../state/PreviewContext'

/** The flow runs in order: sign in, choose a repository, run the task, read the result. */

export function RequireSignedIn({ children }: { children: ReactElement }) {
  return usePreview().signedIn ? children : <Navigate to="/connect" replace />
}

export function RequireRepo({ children }: { children: ReactElement }) {
  const { signedIn, repo } = usePreview()
  if (!signedIn) return <Navigate to="/connect" replace />
  return repo ? children : <Navigate to="/import" replace />
}

export function RequireResult({ children }: { children: ReactElement }) {
  const { signedIn, repo, result } = usePreview()
  if (!signedIn) return <Navigate to="/connect" replace />
  if (!repo) return <Navigate to="/import" replace />
  return result === 'example-passed' ? children : <Navigate to="/check" replace />
}

/** Signing in again once you are signed in just means continuing. */
export function RedirectWhenSignedIn({ children }: { children: ReactElement }) {
  return usePreview().signedIn ? <Navigate to="/import" replace /> : children
}
