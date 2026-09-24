/** The shapes serve.py hands the frontend.  See serve.py `summary()` and `bundle()`. */

export type Kind = 'prompt' | 'harbor'
export type Route = 'openai' | 'anthropic'

export interface Usage {
  input_tokens?: number
  output_tokens?: number
}

/** One line of calls.jsonl: a model request as the proxy saw it on the wire. */
export interface Call {
  n?: number
  ts?: string
  route: Route
  path?: string
  model?: string
  model_requested?: string
  stream?: boolean
  latency_ms?: number
  usage?: Usage
  request?: CallRequest
  response?: CallResponse
  error?: string
}

export interface CallRequest {
  system?: unknown
  messages?: RequestMessage[]
  [key: string]: unknown
}

export interface RequestMessage {
  role: string
  content?: unknown
  tool_calls?: OpenAIToolCall[]
  tool_call_id?: string
}

export interface OpenAIToolCall {
  function?: { name?: string; arguments?: string }
}

/** Anthropic content blocks, the only ones the viewer reads. */
export interface ContentBlock {
  type?: string
  text?: string
  thinking?: string
  name?: string
  input?: unknown
  tool_use_id?: string
  content?: unknown
  is_error?: boolean
  [key: string]: unknown
}

export interface CallResponse {
  choices?: { message?: RequestMessage; finish_reason?: string }[]
  content?: ContentBlock[]
  stop_reason?: string
  [key: string]: unknown
}

/** Per-test results parsed out of verifier/stdout.log when the verifier ran `pytest -v`. */
export interface Tests {
  passed: number
  failed: number
  total: number
  failed_names: string[]
  agent_written: number
  summary?: string | null
  aborted?: string
  cases?: TestCase[] | null
}

export interface TestCase {
  name: string
  file: string
  result: string
  own: boolean
  detail?: string | null
  source?: string | null
}

export interface Harness {
  name?: string
  repo?: string
  commit?: string
  api_style?: string
}

export interface Task {
  name?: string
  taskset?: string
  taskset_dir?: string
}

/** run.json: the origin half written before the run, the result half merged in after. */
export interface RunSummary {
  run: string
  has_run_json: boolean
  kind?: Kind
  harness?: Harness
  task?: Task
  prompt?: string
  model?: string
  workdir?: string
  started?: string
  finished?: string | null
  rc?: number | null
  seconds?: number | null
  reward?: number | string | null
  verifier_rc?: number | null
  errors?: number
  calls?: number | null
  input_tokens?: number | null
  output_tokens?: number | null
  tests?: Tests | null
}

export interface Recipe {
  summary?: string
  api_style?: string
  base_image?: string
  workdir?: string
  run_command?: string
  check_command?: string
  dockerfile?: string
  notes?: string
  env?: { name: string; value: string }[]
}

export interface RunFile {
  name: string
  bytes: number
  core: boolean
}

export interface Verifier {
  'stdout.log'?: string | null
  'stderr.log'?: string | null
  'reward.txt'?: string | null
  tests?: Tests | null
}

/** Everything one run folder holds, as /api/run/<run-id> returns it. */
export interface RunBundle {
  run: string
  run_json: RunSummary
  recipe: Recipe | null
  calls: Call[]
  calls_unparsed: number
  task: string | null
  command: string | null
  stdout: string | null
  stderr: string | null
  proxy: string | null
  verifier: Verifier | null
  files: RunFile[]
}

/** /api/me — whether sign-in is configured at all, and who is signed in. */
export interface Session {
  auth: boolean
  user: GithubUser | null
  install_url: string
  can_clone: boolean
}

export interface GithubUser {
  login: string
  id: number
  name: string | null
  avatar: string | null
}

export interface Installation {
  id: number
  account: string | null
  selection: string | null
}

export interface GithubRepo {
  name: string
  url: string
  private: boolean
  language: string | null
  description: string
}

/** A repository as the picker lists it, real or sampled. */
export interface RepoOption {
  name: string
  language: string
  description: string
  visibility: 'Public' | 'Private'
}
