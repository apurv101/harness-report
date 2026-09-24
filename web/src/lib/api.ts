import type { GithubRepo, Installation, RepoOption, RunBundle, RunSummary, Session } from './types'

/** Every read the frontend makes.  serve.py answers all of them; the static site answers none. */
async function getJSON<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { headers: { Accept: 'application/json' }, signal })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error((body as { error?: string }).error || response.statusText)
  }
  return response.json() as Promise<T>
}

export const getSession = (signal?: AbortSignal) => getJSON<Session>('/api/me', signal)

export const getRuns = (signal?: AbortSignal) => getJSON<RunSummary[]>('/api/runs', signal)

export const getRun = (runId: string, signal?: AbortSignal) =>
  getJSON<RunBundle>(`/api/run/${encodeURIComponent(runId)}`, signal)

export const getInstallations = (signal?: AbortSignal) =>
  getJSON<Installation[]>('/api/github/installations', signal)

export const getRepositories = (installation: number, signal?: AbortSignal) =>
  getJSON<GithubRepo[]>(`/api/github/repos?installation=${encodeURIComponent(installation)}`, signal)

/** Every repository the signed-in user granted, across all their installations. */
export async function getUserRepos(signal?: AbortSignal): Promise<RepoOption[]> {
  const installs = await getInstallations(signal)
  const lists = await Promise.all(installs.map(i => getRepositories(i.id, signal)))
  return lists.flat().map(r => ({
    name: r.name,
    language: r.language || 'Repository',
    description: r.description || '',
    visibility: r.private ? 'Private' : 'Public',
  }))
}

/** A file inside a run folder, served as-is. */
export const rawFileURL = (runId: string, name: string) =>
  `/raw/${encodeURIComponent(runId)}/${name.split('/').map(encodeURIComponent).join('/')}`
