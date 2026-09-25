import { REPO_NAME } from './github'

/**
 * The onboarding preview keeps its progress in sessionStorage so a refresh does not restart it.
 * Stored preview state is never an authentication or verification credential.
 */
const KEY = 'harness-report-site-preview-v1'

export interface PreviewState {
  connected?: boolean
  repo?: string
  /** the chosen repository's GitHub language and description — what the first task is picked from */
  repoMeta?: { language?: string; description?: string } | null
  result?: 'example-passed' | null
  /** the real evaluation the first-task step started (served by serve.py), whatever its outcome */
  evalId?: string | null
}

export function readPreview(): PreviewState {
  let state: unknown
  try { state = JSON.parse(sessionStorage.getItem(KEY) || 'null') } catch { state = null }
  if (typeof state !== 'object' || state === null || Array.isArray(state)) return {}
  const clean = { ...state } as PreviewState
  if (typeof clean.repo !== 'string' || !REPO_NAME.test(clean.repo)) delete clean.repo
  if (typeof clean.evalId !== 'string' || !/^\d{8}T\d{6}-[a-z0-9.-]{1,12}(?:-[a-f0-9]{12})?$/.test(clean.evalId)) delete clean.evalId
  return clean
}

export function writePreview(state: PreviewState): void {
  try { sessionStorage.setItem(KEY, JSON.stringify(state)) } catch { /* private mode: the preview just forgets */ }
}

/** The sample repositories the picker offers before anyone signs in. */
export const SAMPLE_REPOS = [
  { name: 'your-workspace/my-agent', language: 'Python', description: 'Your agent harness', visibility: 'Private' },
  { name: 'your-workspace/research-agent', language: 'TypeScript', description: 'A research assistant', visibility: 'Private' },
  { name: 'SWE-agent/mini-swe-agent', language: 'Python', description: 'Try a public harness', visibility: 'Public' },
] as const

/** The first task, and the four stages the preview walks through while it "runs". */
export const FIZZBUZZ_OUTPUT = '1  2  Fizz  4  Buzz  Fizz  7  8  Fizz  Buzz  11  Fizz  13  14  FizzBuzz'

export const STAGES = [
  ['Fetch repository', 'Read the harness from your selected repository.'],
  ['Prepare environment', 'Set up an isolated environment for your harness.'],
  ['Run FizzBuzz', 'Ask your agent to create and run a small Python program.'],
  ['Verify output', 'Compare the result with the expected output.'],
] as const
