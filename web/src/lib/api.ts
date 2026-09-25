import type { EvalConsole, EvalState, GithubRepo, Installation, RepoOption, RunBundle, RunFiles, RunSummary, Session } from './types'

/** Every call the frontend makes.  serve.py answers all of them; the static site answers none. */
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

/** Just the run's file list — light enough to poll while the run is still writing into the folder. */
export const getRunFiles = (runId: string, signal?: AbortSignal) =>
  getJSON<RunFiles>(`/api/run/${encodeURIComponent(runId)}/files`, signal)

/** A file inside a run folder, served as-is. */
export const rawFileURL = (runId: string, name: string) =>
  `/raw/${encodeURIComponent(runId)}/${name.split('/').map(encodeURIComponent).join('/')}`

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error((data as { error?: string }).error || response.statusText)
  return data as T
}

/** Start run.sh on this repository and the bowling task.  Fails with a message while another one runs. */
export const startEval = (repo: string) => postJSON<EvalState>('/api/evals', { repo })

/** The evaluation running on this machine now, or null. */
export const getCurrentEval = (signal?: AbortSignal) => getJSON<EvalState | null>('/api/evals/current', signal)

/** One evaluation, with run.sh's events from `after` on. */
export const getEval = (id: string, after = 0, signal?: AbortSignal) =>
  getJSON<EvalState>(`/api/evals/${encodeURIComponent(id)}?after=${after}`, signal)

/** run.sh's own terminal output for one evaluation, from byte `after` on. */
export const getEvalConsole = (id: string, after = 0, signal?: AbortSignal) =>
  getJSON<EvalConsole>(`/api/evals/${encodeURIComponent(id)}/console?after=${after}`, signal)

/** The whole console log as plain text, for opening in a tab. */
export const evalConsoleURL = (id: string) => `/api/evals/${encodeURIComponent(id)}/console?format=text`

export const cancelEval = (id: string) => postJSON<{ cancelled: boolean }>(`/api/evals/${encodeURIComponent(id)}/cancel`, {})
