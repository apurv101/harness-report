# Converting a benchmark into Harbor form

Research notes, 2026-09-24. They cover what already exists as Harbor tasks, which ecosystems already have converters, the recipe for each source shape, and a minimal automated convert-and-validate pipeline. Companion data: `harbor-coverage.jsonl` (one line per known Harbor dataset).

## 1. What already exists

| Where | What | Count |
|---|---|---|
| Harbor Hub (`hub.harborframework.com`, Supabase-backed; read with the public key shipped in `harbor` 0.23.0) | public dataset packages | **317 packages, 602,404 task refs** in their latest versions. About 515k of these are training collections (104 packages, mostly OpenThoughts TaskTrove), 17 are test/smoke packages, and the rest are benchmarks: **196 benchmark/subset packages, ~99.7k tasks** |
| Legacy `registry.json` (harbor repo root; `harbor datasets list --legacy`) | name@version entries pointing at git repos | **80 entries, 51,625 tasks**. 69 are also on the Hub. 11 are legacy-only: cooperbench, researchcodebench, spider2-dbt, bird-bench@parity, code-contests, pixiu, ml-dev-bench, swebench_multilingual, spreadsheetbench-verified, gso, terminal-bench-sample |
| Upstream `harbor/adapters/` @ main (31668af, 2026-09-25) | adapter source packages | **85 adapters**, the same set as the local corpus's pinned 8828a30 |
| Local `~/Desktop/harbor-tasks` | 100 dataset directories (85 under `datasets/`, 8 under `hub-datasets/`, 6 legacy top-level collections, and 1 `optional-tasks`) | **93,550 task folders**, including overlapping variants. 33,786 of them are GraphicDesignBench |

Merged into `harbor-coverage.jsonl`: **358 rows**, 307 distinct benchmark ids. Counting only benchmark and subset rows, there are 237 datasets and ~125.8k tasks: 132 are registry-only (27.7k tasks), 75 are in both the registry and the local corpus (71.8k), and 30 are local-only (26.3k). The local-only datasets were generated from adapters but never registered, for example HLE, SWE-Gym, Multi-SWE-bench, CyberGym, GAIA2, OmniMath, CRMArena, SciCode, and WideSearch. **106 rows are backed by an upstream adapter.** The rest are Harbor-native, published straight to the Hub by their authors: blobfish, scale-ai, terminal-bench, datacurve, mercor, and others.

`harbor datasets list` (0.23.0) now only prints a link to the Hub website. `--legacy` shows the 80-entry registry.json table. The Hub has no public list endpoint in the CLI. We enumerated it with PostgREST: `package?type=eq.dataset`, `dataset_version`, `dataset_version_tag`, `dataset_version_task` (count), and `task_version_file` (sampled 3 tasks per dataset to detect compose files and `solution/`). 23 of the 196 Hub benchmark packages ship no `solution/` in the sampled tasks, which means there is no oracle. These are mostly LLM-judge and rubric sets such as harvey lab, chi-bench, and UserBench.

## 2. Converters between ecosystems (both directions)

| Ecosystem | Its task shape | Harbor → it | It → Harbor | Ingest cost |
|---|---|---|---|---|
| **verifiers (Prime Intellect) v1** | Python `Taskset` of `TaskData` rows + harness + rubric; envs are pip packages exposing `load_environment()` | **Yes.** `verifiers.v1.tasksets.harbor.HarborTaskset`: name a Harbor dataset (`org/name@ver`, registry/repo/path) and it loads tasks. Gaps: no sidecar services, no multi-step, no building verifier images (pre-built only), and ENTRYPOINT is replaced with keepalive, so compose tasks do not run | **None found.** No exporter from a verifiers env to task folders | Medium. Each env is arbitrary Python (reward fns, often LLM judges, tool envs). Needs a per-shape wrapper, see 3a |
| **OpenEnv (Meta/HF)** | HTTP/WebSocket server in Docker (`reset`/`step`/`state`), `openenv.yaml`, typed Action/Observation models; ~40 envs in `meta-pytorch/OpenEnv/envs` | **Yes.** `envs/harbor_env` wraps any Harbor dataset (HF repo, dir, or registry name) as an OpenEnv with a `run_rollout` MCP tool, a capture proxy, and 16 harnesses × 23 sandboxes. `envs/tbench2_env` is TB2-specific | **None found.** verifiers has an `OpenEnvTaskset` that plays OpenEnv servers, which is the pattern to copy | Medium. The server becomes a compose sidecar, and the `step` loop has to be exposed to a terminal agent as a CLI or MCP tool (KUMO / τ³ pattern) |
| **NeMo Gym (NVIDIA)** | resources server (FastAPI: tools + `verify`) + agent server + JSONL rows (`responses_create_params`, verifier metadata) | **Yes.** `responses_api_agents/harbor_agent` (merged) runs Harbor agents and envs inside Gym, including Singularity and Daytona. Open PRs #3673 (load Harbor folders and Hub datasets as rows) and #3674 (Harbor resources server) add native `harbor:<dataset>` refs | **Partial.** No NVIDIA exporter, but OpenThoughts TaskTrove already republished NeMo-Gym data as Harbor tasks (`openthoughts/tasktrove-nemotron-gym-*`, ~130k tasks, instruction-following, calendar, workplace, and competitive coding). The pipeline is `marin-community/marin` PR #9061 (merged): 19 converters, 12 verifier modes, and `tests/verifier.toml` grader contracts | Low for single-turn rows (reuse the TaskTrove approach). High for stateful resources servers (port as sidecar) |
| **Inspect / UK AISI inspect_evals** | `@task` → `Dataset[Sample(input, target, metadata, files, setup)]` + `solver` + `scorer` + `sandbox` (docker compose); 137 evals in `inspect_evals` | **Yes.** `meridianlabs-ai/inspect_harbor` (v1.0.0, 2026-09-23; no longer depends on `harbor`) runs any registry, Hub, git, or local Harbor dataset as an Inspect task. inspect_evals removed its own `harbor_task()` and points to it | **None found.** No inspect → Harbor exporter exists. Harbor has hand-written adapters for several benchmarks that are also Inspect evals (GPQA, GAIA, SimpleQA, MMMLU, StrongREJECT, SciCode, …) | Low–medium. Samples and compose sandboxes map almost 1:1. Scorers must be re-hosted in `tests/` (see 3c) |
| **Terminal-Bench 1 / t-bench** | `task.yaml` + `docker-compose.yaml` + `run-tests.sh` | n/a | **Yes, built in.** `harbor task migrate` (`harbor.mappers.terminal_bench.TerminalBenchMapper`), used by ABC-Bench | Trivial |
| **Harbor native** | `instruction.md`, `task.toml`, `environment/`, `tests/test.sh` → `/logs/verifier/reward.{txt,json}`, optional `solution/solve.sh` | — | `harbor exec -p <paths> -i "<instruction>"` compiles paths plus an instruction into tasks (experimental). `harbor init`/`harbor adapter init` scaffold new tasks or adapters | — |

Summary: **every major ecosystem can already consume Harbor.** Converters in the other direction exist only for Terminal-Bench (built in) and NeMo-Gym-style row data (TaskTrove / marin). Nothing converts verifiers envs, OpenEnv servers, or inspect_evals tasks into Harbor tasks, and that gap is ours to fill.

## 3. Recipe per source shape

Every recipe produces the same thing. Each task gets a folder containing a unique, stable `[task].name` (`org/slug`). `instruction.md` must never hold the answer. `environment/Dockerfile` should use one of the 8 bases that cover 81% of the corpus. `tests/test.sh` writes a number between 0 and 1 to `/logs/verifier/reward.txt`, or a dict to `reward.json`. `solution/solve.sh` is the oracle. A `dataset.toml` lists the tasks.

### 3a. pip-package environment (verifiers env, reasoning-gym, textarena, a `load_environment()` lib)
1. Install the package in the Dockerfile at a pinned version. Enumerate rows with `load_environment(...).dataset` or the library generator at a fixed seed, one task per row. Harbor's reasoning-gym adapter does this: 576 tasks from seeded generators.
2. The row prompt becomes `instruction.md`, with an explicit answer path such as `/app/answer.txt`.
3. Serialise the row's answer and metadata into `tests/` (the agent can't see it). `test.sh` calls the package's own reward function on the answer file, so the scoring code is reused, not reimplemented.
4. The oracle writes the known answer.
- Multi-turn/tool envs: the env's tools become a CLI in the image or an MCP sidecar, and state carries across calls (see 3b).
- **Cost: low** for single-turn envs, fully mechanical, about ¼ day per package. **Medium** for tool/multi-turn envs. **Risk:** reward fns that call an LLM judge (see 3d), and generator seeds that make the task identity unstable.

### 3b. OpenEnv HTTP server (or any stateful simulator: NeMo Gym resources server, τ-bench, KUMO)
1. `environment/docker-compose.yaml`: the `main` agent container plus an `env` service built from the OpenEnv image, with `reset(task_args)` run at start via a healthcheck or entrypoint.
2. Expose `step` to the agent. A thin CLI (`envctl act '<json>'`) or an MCP server is declared in `task.toml`. τ³-bench, GAIA2-cli and KUMO are the three worked examples in the local corpus.
3. Hidden state and the grader live in the env service or verifier image, never in `main` (KUMO puts secrets in the verifier image).
4. `test.sh` queries the env for `state` and cumulative reward and writes the reward. Per-step rewards get summed, as in verifiers' `OpenEnvTaskset`.
5. The oracle is a scripted action sequence if the env has one. Otherwise it's a replay of a known-good trajectory, and if neither exists, a model-found solution confirmed by a human (upstream's "benchmarks without oracle" route).
- **Cost: high**, 1–5 days per env. Parity is hard because the interaction protocol differs from the source's. Multi-container, so it **will not run under verifiers' HarborTaskset**, which has no sidecars.

### 3c. Inspect task (inspect_evals)
1. Each `Sample` becomes a task. `input` becomes `instruction.md`, and `files`/`setup` go into `environment/`. The eval's `sandbox=("docker", "compose.yaml")` becomes `environment/docker-compose.yaml` almost verbatim.
2. Store `target` and `metadata` in `tests/`.
3. The scorer is the hard part. For `match`, `includes`, `choice` and `pattern`, re-implement the scorer in about 20 lines of Python inside `test.sh`. For custom scorers that read sandbox state, run the scorer code in the verifier, copying the eval module into `tests/`. For `model_graded_*`, see 3d.
4. Solver-specific scaffolding (system prompts, `basic_agent` tools, message limits) becomes instruction text and `task.toml` limits, and parity should be checked against Inspect's `react()` agent.
5. For the oracle, a `target` string is written to the answer file. Agentic CTFs need the flag, and inspect_evals CTFs usually ship solution scripts.
- **Cost: low–medium.** Structurally the closest source to Harbor. A generic `inspect → harbor` compiler covering the built-in scorers would convert most of the 137 evals mechanically.

### 3d. Plain dataset + LLM judge (QA, rubric, legal and finance drafting, SimpleQA/HLE-style)
1. One row becomes one task, following the AIME/HLE/SimpleQA adapter pattern. `instruction.md` holds the question plus the answer path.
2. `test.sh` runs a judge script with the reference answer and rubric in `tests/`. `task.toml` `[verifier.env]` carries `MODEL_NAME` and the API key through `${VAR}` passthrough, and the network must allow the judge endpoint.
3. Pin the judge model, prompt and temperature. Record the judge in dataset metadata, because a different judge means a different benchmark.
4. The oracle writes the reference answer. For rubrics, write a gold response. Many Hub rubric sets have none: 23 of 196 sampled packages had no `solution/`.
- **Cost: lowest to convert** (hours, fully automatic), **highest to validate**. Judge variance means the no-op-scores-0 gate is only approximate. Every eval run incurs judge cost, and verifier network egress is required.

### 3e. Repo + tests (SWE-bench family, feature/refactor/test-writing, CRUST-bench, DevOps-Gym)
1. Each instance gets a Dockerfile that checks out `repo@base_commit` and installs dependencies. Prefer the benchmark's prebuilt per-instance image (`swebench/*`, `xingyaoww/*`, `jefzda/*`), because rebuilding is where adapters break.
2. The issue or feature text goes in `instruction.md`.
3. `tests/` gets the test patch plus FAIL_TO_PASS and PASS_TO_PASS lists. `test.sh` applies the test patch, runs the named tests and writes 1 only if all of them pass.
4. The oracle applies the gold patch.
5. Scrub git history and network access, because agents can fetch the upstream fix. cais/swebenchpro exists specifically to add that isolation.
- **Cost: medium** per benchmark, but it is the most mechanical shape at scale. SWE-smith, SWE-rebench and TaskTrove converted 10k–18k instances each. **Risks:** image size (1–2 GB per task, 88% of distinct base images are single-use), flaky tests, and nondeterministic PASS_TO_PASS.

## 4. QA gates (what upstream requires and what we should automate)

From `harbor/adapters/ADAPTER_CONTRIBUTING.md` and the local corpus's parity files:

1. **Structure.** Each task folder has `task.toml` (parses, includes `name`, and names are unique and stable across reruns), `instruction.md`, `environment/Dockerfile` (or `docker_image`), `tests/test.sh`, and `solution/solve.sh`. Run `harbor adapter review` for structure and code quality, and `harbor check <path>` for the LLM rubric review of task quality (defaults: claude-code + sonnet). No canary strings in the Dockerfile.
2. **Oracle = 1.0 on 100% of tasks.** `harbor run -p <dir> -a oracle`. Where the oracle fails, cross-check on the original benchmark to separate a broken source oracle from a broken adaptation. Exclude or flag known-broken instances; Spider2-DBT dropped 4 and DA-Code dropped 21.
3. **No-op = 0.0 on 100% of tasks.** `harbor run -a nop`. This catches verifiers that pass on an untouched workspace, answer files pre-seeded in the image, and tests that exit 0 without writing the reward. Upstream doesn't list this as a gate, but the `nop` agent exists and we should require it.
4. **Determinism.** Rerun oracle and nop twice. Any change in reward is flakiness, which matters most for repo tests, network fetches and LLM judges.
5. **Leakage.** Grep `instruction.md` and the agent image for the answer or gold patch. Hidden state belongs only in `tests/` or in the verifier image or sidecar. Check whether network access lets the agent fetch the upstream fix.
6. **Parity** (upstream's acceptance bar). Run the same agent and model on the original and Harbor sides, at least 2 runs each (3 or more preferred), and report mean ± sample SEM. The two sides match only if their run ranges overlap. Record in `parity_experiment.json`. For expensive benchmarks, a `--split parity` subset is published with the `@parity` tag.
7. **Solvability smoke** (when there's no oracle). Have a cheap agent sweep all tasks, then use successful trajectories as oracles and escalate the rest to a strong model plus a human.

## 5. A minimal automated convert-and-validate pipeline

```
source spec ──► shape classifier ──► shape template (3a–3e) ──► task folders + dataset.toml
                                                                     │
      ┌──────────────────────────────────────────────────────────────┘
      ▼
 static lint (toml schema, names, required files, leakage grep, canary) ──► harbor adapter review / harbor check
      ▼
 build images (cache the 8 head bases; per-instance tail images pulled, not built)
      ▼
 oracle run ×2  (must be 1.0)   +   nop run ×2 (must be 0.0)   on every task
      ▼
 cheap-agent smoke on a sample (catches unsolvable/underspecified instructions, env missing tools)
      ▼
 status: harbor_status = converted | converted-no-oracle | failed-oracle | failed-nop | needs-sidecar
      ▼
 (optional, gated) parity on a subset vs the source harness ──► publish to Hub (org/name@version, tags latest/parity)
```

What it needs:
- **A source spec per benchmark** (from the catalog): data URL and revision, license, split, shape, answer field, scorer type, and judge model if any.
- **Five shape templates** (3a–3e) written as `harbor adapter init` templates. Most rows fill a template without custom code. An LLM writes only the scorer glue, and the gates check it.
- **Run plane:** Docker on amd64 (see harness-report's `run.sh`/RUN-PLANE, local matches AWS). The oracle and nop agents are free, so the gates cost only compute. Budget about 2 × (build + verify time) per task.
- **Judge credentials and egress** for 3d tasks, via `[verifier.env]` passthrough.
- **Provenance** in each dataset: source revision, adapter commit, content hash, and gate results. Hub versions are content-addressed, which gives this for free.
- **A status writer** that feeds `harbor_status` back into `catalog/index.jsonl`.

## 6. Top risks for automated conversion

1. **Scorer fidelity.** The reward is the benchmark. A re-implemented scorer that passes oracle and nop can still disagree with the original on real agent outputs, for example through answer normalisation or tolerance. Only parity catches this, and parity costs model runs.
2. **No oracle.** Rubric and judge datasets (23/196 sampled Hub benchmarks) and many interactive envs have no reference solution, so gate 2 can't run. Their outputs should be marked `converted-no-oracle`, never `validated`.
3. **LLM-judge verifiers.** They are nondeterministic and cost money on every eval. Judge drift silently changes the benchmark, so the judge has to be pinned and recorded.
4. **Stateful and multi-container envs.** 69 of 358 coverage rows are multi-container. These tasks are the most expensive to write, the hardest to prove parity for, and don't run in verifiers' HarborTaskset.
5. **Image supply.** The SWE-style tail needs one 1–2 GB image per task, and upstream images drift or vanish. Rebuilding from source is where adapters break (DevOps-Gym has 5 tasks missing `test.sh`).
6. **Leakage and contamination.** Answers baked into images, readable git history, or open network access to upstream fixes all inflate scores, and nop=0 doesn't detect them.
7. **Identity churn.** The same benchmark appears as many Hub packages (14 Terminal-Bench packages across 2.0, 2.1, 3 and 4, 3 SWE-rebench, 2 SWE-bench Pro, 2 Harvey LAB, and 4 τ³ repackagings). Versions are not semantic: `terminal-bench/terminal-bench@3.0.1` is TB 4.0 per its tags. Dedup therefore needs content hashes, not names.
8. **Licensing and gating.** Private test sets (GAIA test, orca-bench-private), gated HF datasets, and per-benchmark licences that Harbor's licence does not cover.
