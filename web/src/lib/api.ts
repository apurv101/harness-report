import type {
  EvalConsole, EvalState, FirstTask, GithubRepo, HarnessCard, HarnessPageData, Installation, Recs, RepoOption, RunBundle,
  RunFiles, RunSummary, Session, TaskCard, TaskPageData, TasksetCard, TasksetPageData,
} from './types'

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

/** Start run.sh on this repository and one runnable task (the server's pick when none is given).  Fails with a
 *  message while another one runs, for a task the site does not offer, or over the daily limit. */
export const startEval = (repo: string, pick?: { taskset: string; task: string } | null) =>
  postJSON<EvalState>('/api/evals', pick ? { repo, taskset: pick.taskset, task: pick.task } : { repo })

const seg = encodeURIComponent

/** Every harness that has been run, with its tallies. */
export const getHarnesses = (signal?: AbortSignal) => getJSON<{ harnesses: HarnessCard[] }>('/api/harnesses', signal)

/** One harness: its card, what it is for, the tests recommended next, and its runs. */
export const getHarness = (name: string, signal?: AbortSignal) => getJSON<HarnessPageData>(`/api/harnesses/${seg(name)}`, signal)

/** The tests recommended next for a harness, or null before anything has ranked them. */
export const getRecs = (name: string, signal?: AbortSignal) => getJSON<Recs | null>(`/api/harnesses/${seg(name)}/recs`, signal)

export const getTasksets = (signal?: AbortSignal) =>
  getJSON<{ tasksets: TasksetCard[]; domains: string[] }>('/api/tasksets', signal)

/** One page of a taskset's tasks; `after` is the cursor the previous page returned. */
export const getTaskset = (taskset: string, after?: string | null, signal?: AbortSignal) =>
  getJSON<TasksetPageData>(`/api/tasksets/${seg(taskset)}${after ? `?after=${seg(after)}` : ''}`, signal)

export const getTask = (taskset: string, task: string, signal?: AbortSignal) =>
  getJSON<TaskPageData>(`/api/tasks/${seg(taskset)}/${seg(task)}`, signal)

/** Every task the site can start. */
export const getRunnable = (signal?: AbortSignal) => getJSON<{ tasks: TaskCard[] }>('/api/runnable', signal)

/** The task a repository should start with, from its recommendations or, before any run, its language and description. */
export const getFirstTask = (repo: string, meta?: { language?: string; description?: string }, signal?: AbortSignal) => {
  const q = new URLSearchParams({ repo })
  if (meta?.language && meta.language !== 'Repository') q.set('language', meta.language)
  if (meta?.description) q.set('description', meta.description)
  return getJSON<FirstTask | null>(`/api/first-task?${q}`, signal)
}

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
