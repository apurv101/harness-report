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

/**
 * One line of egress.jsonl: a connection the agent's container tried to open, as the egress proxy saw it.
 * `allowed` is the verdict, `rule` the reason for it, and `phase` says whether the agent or the verifier asked.
 */
export interface Egress {
  n?: number
  ts?: string
  phase?: string
  kind?: string
  method?: string
  host?: string
  port?: number
  url?: string | null
  allowed?: boolean
  rule?: string
  status?: number | null
  bytes_up?: number
  bytes_down?: number
  ms?: number
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
  /** every connection the container attempted; the proxy's clock, not the host's */
  egress: Egress[]
  task: string | null
  command: string | null
  stdout: string | null
  stderr: string | null
  proxy: string | null
  verifier: Verifier | null
  files: RunFile[]
  /** files past the stored manifest's cap (0 when the folder was read directly) */
  files_omitted: number
  /** where this answer came from: the run folder, or the DynamoDB rows */
  source: 'files' | 'table'
  /** names whose stored text lost bytes to the item limit — open the raw file for the whole thing */
  truncated: string[]
}

/** GET /api/run/<run-id>/files — the cheap poll while a run is still writing. */
export interface RunFiles {
  run: string
  files: RunFile[]
  files_omitted: number
  source: 'files' | 'table'
}

/** GET /api/evals/<id>/console — run.sh's own output from a byte cursor on. */
export interface EvalConsole {
  text: string
  /** the byte to ask from next time */
  next: number
  /** the log's size on disk */
  bytes: number
  status: EvalStatus
}

/** /api/me — whether sign-in is configured at all, and who is signed in. */
export interface Session {
  auth: boolean
  local_users?: boolean
  eval_mode?: string
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

/** One evaluation started from the site: run.sh on a repo × one runnable task.  See evals.py. */
export type EvalStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled'

export interface Evaluation {
  id: string
  repo: string
  url: string
  taskset: string
  task: string
  /** runs/<run>: the run folder, listed on the Runs page from the moment it starts */
  run: string
  harness?: string
  user?: string | null
  status: EvalStatus
  started: string
  finished?: string | null
  rc?: number | null
  cancelled?: boolean
  error?: string | null
  queue_position?: number
  execution_started?: string
}

/** One line run.sh writes with HR_EVENTS set. */
export interface EvalEvent {
  ts: number
  type: 'stage' | 'fetched' | 'recipe' | 'built' | 'run' | 'result' | 'error' | string
  stage?: string
  t?: number
  msg?: string
  mode?: 'reused' | 'analyzed' | 'failed'
  seeded_from?: string
  commit?: string
  reward?: number | null
  [key: string]: unknown
}

/** The model calls so far, read from the run's calls.jsonl as it grows. */
export interface EvalLive {
  calls: number
  input_tokens: number
  output_tokens: number
  errors: number
  last_action: string | null
}

/** What GET /api/evals/<id>?after=<n> answers. */
export interface EvalState {
  eval: Evaluation
  events: EvalEvent[]
  next: number
  live: EvalLive
  /** the run's summary (reward, tests, calls) once it has finished */
  result: RunSummary | null
}

/* ---------------------------------------------------------------- harnesses, tasks, recommendations (lib/pages.py) */

/** How one harness did on one task, or one task by one harness: runs folded, newest last. */
export interface Outcomes {
  runs: number
  passes: number
  last?: string | null
  last_run?: string | null
  last_outcome?: 'pass' | 'fail' | 'error' | 'running'
  last_reward?: number | string | null
  last_tests?: Tests | null
}

export interface HarnessProfile {
  use_case?: string | null
  domains?: string[]
  languages?: string[]
  capabilities?: string[]
  not_for?: string[]
  evidence?: string
  source?: string
  commit?: string
}

export interface HarnessCard {
  harness: string
  repo?: string | null
  commit?: string | null
  api_style?: string | null
  summary?: string | null
  runs: number
  finished: number
  passes: number
  tasks_tried: number
  tasks_passed: number
  tasksets?: string[]
  results?: Record<string, Outcomes>
  models?: string[]
  last_run?: string | null
  last_run_id?: string | null
  use_case?: string | null
  domains?: string[] | null
}

export interface Rec {
  taskset: string
  task: string
  why?: string | null
  score?: number | null
  domain?: string | null
  language?: string | null
}

export interface Recs {
  recs: Rec[]
  source: 'llm' | 'rules' | string
  based_on_run?: string | null
  at?: string
}

/** A run cut to what a list needs (lib/pages.py run_row). */
export interface RunRow {
  run: string
  started?: string
  harness?: string | null
  task?: { taskset?: string; name?: string } | null
  model?: string
  reward?: number | string | null
  tests?: Tests | null
  calls?: number | null
  seconds?: number | null
  outcome: 'pass' | 'fail' | 'error' | 'running'
}

export interface HarnessPageData {
  harness: HarnessCard
  profile: HarnessProfile | null
  recommendations: Recs | null
  runs: RunRow[]
}

export interface TasksetCard {
  taskset: string
  path?: string
  n_tasks: number
  n_runnable: number
  domain?: string | null
  languages?: string[]
  categories?: string[]
  owner_org?: string | null
  grading?: string | null
  task_kind?: string | null
  url_repo?: string | null
  url_paper?: string | null
  name?: string | null
  sample_instruction?: string | null
}

export interface TaskCard {
  taskset: string
  task: string
  difficulty?: string
  category?: string
  language?: string
  tags?: string[]
  runnable?: boolean
  compose?: boolean
  instruction?: string | null
  instruction_truncated?: boolean
  agent_timeout?: number
  oracle?: { reward?: number | string | null; platform?: string; at?: string } | null
  results?: Record<string, Outcomes>
  runs?: number
}

export interface TasksetPageData { taskset: TasksetCard; tasks: TaskCard[]; next: string | null }
export interface TaskPageData { task: TaskCard; runs: RunRow[] }

/** What the site suggests a repo starts with (GET /api/first-task). */
export interface FirstTask extends Rec {
  source: string
  harness: string
  recs: Rec[]
}
