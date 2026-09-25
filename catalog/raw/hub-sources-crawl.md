# Hub sources crawl: Hugging Face + Kaggle

Swept 2026-09-24. Output: `hub-sources.jsonl` (399 rows: 250 HF datasets, 43 HF Spaces, 74 Kaggle Benchmarks, 26 Kaggle competitions, 6 Kaggle datasets). This file records what worked, how noisy each query is, and the crawl we should put on a schedule.

## 1. Endpoints that worked

### Hugging Face (no auth)

| What | Endpoint | Notes |
|---|---|---|
| Dataset search | `GET https://huggingface.co/api/datasets?search=<q>&limit=100&full=true&sort=downloads` | `search` is a substring match on the repo id, not the card. `sort` accepts `downloads`, `likes`, `lastModified`, `trendingScore`. `full=true` adds `cardData` (license, task_categories, configs/splits, `dataset_info` with `num_examples`), `tags`, `downloads`, `likes`, `lastModified`, `gated`, and a 500-char `description`. |
| Tag filter | `...?filter=<tag>` (repeatable), e.g. `filter=harbor`, `filter=benchmark:official`, `filter=task_categories:text-generation&search=bench` | Tags are free-form, and tag filters had the best hit rates in the whole sweep (§3). |
| Org enumeration | `...?author=<org>&limit=100&full=true` | Some orgs have no datasets: `UKGovernmentBEIS`, `METR`, `openenv`, `tau-bench`, `OSU-NLP-Group`, `google-deepmind`, `all-hands`, `WebArena`. The UK AISI publishes as `ai-safety-institute`. |
| Pagination | Response header `Link: <...&cursor=...>; rel="next"` | Follow it until it's gone. `filter=openenv` on Spaces returned more than 3,000 before I stopped. |
| One repo | `GET https://huggingface.co/api/datasets/<id>` | The same fields as `full=true`, for a single repo. |
| Card text | `GET https://huggingface.co/datasets/<id>/raw/main/README.md` | Regex it for `github.com/<o>/<r>` and `arxiv.org/abs/<id>` (`arxiv:` tags aren't always set). This fails on gated repos, which are about 9% of curated rows (23 of 250). |
| Spaces | `GET https://huggingface.co/api/spaces?filter=agent-environment` (27), `filter=openenv` (3,000+), `search=leaderboard&sort=likes` (1,714), `filter=leaderboard&sort=likes` (1,032), `search=arena` (989) | `cardData.short_description` is the most useful single field. |

**Rate limit:** the response header is `ratelimit: "api";r=<remaining>;t=<secs>` with `ratelimit-policy: "fixed window";"api";q=500;w=300`, so 500 requests per 5 minutes per IP, unauthenticated. The sweep used about 330 requests (270 of them for per-repo enrichment) and got no 429s. With an HF token the quota is higher, but a token isn't needed.

**Two discovery sources I didn't expect:**
- **`filter=benchmark:official`** (47 repos) and **`filter=benchmark:eval-yaml`** (48). These are HF's own benchmark registry: datasets with an `eval.yaml` that get a leaderboard on the dataset page. It covers Terminal-Bench 2/2.1/3, SWE-bench Verified/Pro/Multilingual, APEX-Agents, chi-Bench, SkillsBench, Deep-SWE, Toolathlon, WildClawBench, Claw-Eval, YC-Bench, LHTB and others. **It's the highest-precision feed on either platform (§3).**
- **`filter=harbor`** (195 repos). People are already publishing Harbor task folders on HF: harborframework/*, FineEnvs/repo2rlenv-* (about 20), open-athena/nemotron-gym-* (NeMo Gym converted to Harbor, about 20), laion/*-apptainer, mercor/apex-*-harbor, datacurve/deep-swe, SamuelChien821/*bench-100, and more. At least 20% of these are trajectory or eval-run dumps, not task sets (§4).

`evaleval/EEE_datastore` ("Every Eval Ever", 60k downloads) is a community database of eval results in one schema. It's a good way to discover benchmark names. It isn't a benchmark, so it's not in the jsonl.

### Kaggle

| What | Endpoint | Auth |
|---|---|---|
| Datasets search | `GET https://www.kaggle.com/api/v1/datasets/list?search=<q>&sortBy=votes&page=<n>` | **Works unauthenticated.** |
| Competitions (public API) | `GET https://www.kaggle.com/api/v1/competitions/list?search=...` | **401 Unauthenticated.** A `kaggle.json` key would unlock it. It's not needed because of the next row. |
| Competitions (site-internal) | `POST https://www.kaggle.com/api/i/competitions.CompetitionService/ListCompetitions` with body `{"selector":{"listOption":"LIST_OPTION_DEFAULT","sortOption":"SORT_OPTION_NEWEST","searchQuery":"<q>"},"pageSize":100,"pageToken":"<tok>"}` | Anonymous session: `GET https://www.kaggle.com/benchmarks` with a cookie jar, then send the `XSRF-TOKEN` cookie value as the `x-xsrf-token` header. Returns all 754 listed competitions with `totalTeams`, `hostName`, `deadline`, `simulation`, `hackathon`, `reward`. |
| **Kaggle Benchmarks** | `POST https://www.kaggle.com/api/i/benchmarks.BenchmarkService/ListBenchmarks` with body `{"pageSize":100,"pageToken":"<tok>"}` | Same XSRF cookie trick. Returns all **1,107** benchmarks: `type` is INDIVIDUAL (1,076), GAME (19) or SUITE (12). Each row has `organization{slug,name}` or an owner user, `viewCount`, `voteCount`, `version.description`, `version.citation.url`, `version.leaderboardModelVersionsCount`, `childTaskVersionMappingsCount`, `competitionId`, and `media[]` (GitHub harness links, arXiv, replay datasets). |

The canonical benchmark URL is `https://www.kaggle.com/benchmarks/<org-slug or username>/<slug>`, confirmed against `version.citation.url`.

The internal `/api/i/` endpoints are undocumented and could change. If they break, a Kaggle API key and the v1 API cover competitions. There's no v1 endpoint for Benchmarks, so we'd have to scrape the page instead. The Kaggle sweep never hit a rate limit (about 30 requests, 0.4 s apart).

**What Kaggle Benchmarks holds:**
- 139 benchmarks are org-owned: Kaggle, Google, Google DeepMind, OpenAI, Meta, IBM Research, Cohere Labs, LlamaIndex, HeyGen, Gert Labs, and the "Open Benchmarks" org that re-hosts GPQA/MMLU/LiveCodeBench/SciCode/MGSM.
- 968 are community-built. Most come from the "Measuring Progress Toward AGI – Cognitive Abilities" hackathon (competition `kaggle-measuring-agi`) and are small cognitive probes.
- The agent-relevant groups:
  - **Game Arena**: 19 GAME benchmarks plus 2 suites, each with a GitHub harness in `Kaggle/kaggle-environments`.
  - **IBM Enterprise Ops**: ITBench plus AssetOpsBench.
  - **Research/search**: Google DeepSearchQA and FACTS Search, OpenAI BrowseComp.
  - **Gert Labs Adversarial Customer Service**.

## 2. Telling a benchmark from a training set, automatically

The scorer in the sweep (`s >= 2.5` kept 1,856 of 9,448 unique HF datasets) combined the signals below. Hand curation then kept 250.

| Signal | Leans benchmark | Leans training/dump |
|---|---|---|
| Tags | `benchmark:official`, `benchmark:eval-yaml`, `benchmark`, `evaluation`, `agent-benchmark`, `not-for-training`, `evaluation-only`, `do-not-train`, a canary GUID in the card | `sft`, `dpo`, `distillation`, `agent-traces`/`agentic-traces`, `trajectories`, `rollouts`, `synthetic`, `training-data`, `rl` alone, `curriculum` |
| Splits (`cardData.configs[].data_files[].split` or `dataset_info.splits`) | only `test`, `dev`, `validation`, `verified`, `lite`, `hard`, `public_release`, or named subsets | only `train` (weak: many benchmarks are uploaded as a lone `train` split, e.g. apex-agents, AIME, ResearchClawBench) |
| Size (`size_categories`) | `n<1K` or `1K<n<10K` | `100K<n<1M` and up (exceptions: SWE-rebench, SWE-rebench-V2, Paper2Arm) |
| Repo name | `bench`, `eval`, `verified`, `-lite`, `arena`, `exam`, `leaderboard` (but `-leaderboard` datasets are often *results*) | `-SFT`, `-RL`, `-traj`, `-trajs`, `-traces`, `-logs`, `-runs`, `-results`, `-predictions`, `-eval-<model>`, `reeval<n>` |
| Card text | "tasks", "verifier", "tests", "oracle", "reward", "leaderboard", "held-out" | "fine-tune", "post-training", "samples generated by", model names in the repo id |
| Owner pattern | org that also owns a GitHub eval repo | personal accounts pushing dozens of near-identical rows (e.g. `Stage-jh-monitor/*-reeval*`, `violetxi/tb2-eval-*`, `dougalldeepmind/2026-*`) |
| Harbor shape | `tags` include `harbor` and the card mentions `task.toml`/`tests/`, "oracle=1 / nop=0", or the Harbor Visualiser | `harbor` plus `atif`/`agent-trajectories`/`sft`: these are run outputs |

**Precision problems I saw:**
- `-leaderboard` datasets are mostly results tables.
- Many "benchmark" hits are OCR, retrieval (mteb) or ASR: 35% of the scored set. Exclude by tag prefix `mteb`, `task_categories:automatic-speech-recognition|text-retrieval|image-*|video-*`, or when `modality:` doesn't include text.
- `open-llm-leaderboard/*` (100+ `details_*` and `requests` datasets) is pure noise. Drop the author.
- Mirrors: SWE-bench Verified had about 30 re-uploads, Terminal-Bench 2.0 about 10, SWE-bench Lite about 15. Collapse them on a canonical-name key (§5).

## 3. Signal-to-noise per query (HF datasets)

`returned` counts rows from one page of 100 (or from full pagination for tag filters). `bench%` is the share the automatic scorer called benchmark-like. `curated%` is the share that survived hand curation into the jsonl.

| Query | returned | bench% | curated% | Verdict |
|---|---|---|---|---|
| `filter=benchmark:official` (paged) | 47 | ~100 | **53** | best single feed; run daily |
| `filter=benchmark:eval-yaml` (paged) | 48 | ~100 | 48 | same set plus a few eval-yaml-only |
| `filter=agents` | 100 | 55 | **36** | excellent |
| `filter=harbor` (paged) | 195 | 51 | 18 (31 on first page) | excellent, and already in Harbor shape; filter out trajectory dumps |
| `filter=benchmark` | 100 | 77 | 27 | good |
| `filter=task_categories:text-generation&search=bench` | 100 | 80 | 26 | good |
| `filter=agent` | 100 | 33 | 19 | good |
| `search=swe-bench` | 149 | 87 | 14 | many mirrors |
| `filter=code` | 100 | 25 | 13 | ok |
| `filter=rl-environment` | 73 | 24 | 12 | ok; mostly RL pools |
| `filter=evaluation`, `filter=tool-use` | 100 | 63 / 21 | 12 / 11 | ok |
| `search=swe`, `terminal`, `harbor`, `terminal-bench` | 100–194 | 28–44 | 6–9 | fair; mirrors and run dumps |
| `search=agent`, `web`, `finance bench`, `crm`, `browsecomp`, `bird`, `webarena` | 32–255 | 8–75 | 3–5 | fair |
| `search=benchmark`, `eval`, `evaluation`, `leaderboard` | 100–265 | 25–50 | ≤2 | poor: dominated by general LLM evals and results |
| `search=agentic`, `trajectories`, `tool-use`, `tool use`, `environment`, `gym`, `verifiable`, `verifier`, `rubric`, `mcp`, `appworld`, `tau-bench`, `osworld`, `gui`, `android`, `browser`, `computer-use` | 20–187 | 0–67 | 0–2 | **noise**: training/trajectory corpora dominate |
| domain words `legal`, `tax`, `chip`, `verilog`, `rtl`, `sql`, `text-to-sql`, `spreadsheet`, `excel`, `insurance`, `accounting`, `cybersecurity`, `ctf`, `lean`, `formal`, `robotics`, `minecraft`, `embodied`, `game`, `customer service` | 1–100 | 0–51 | 0–9 | low precision, but they surface one or two domain gems each (TitanBench, HWE-bench, TaxBench-AU, Crypto-Accounting-Bench, ShortcutBench, Alibaba CTF) |

**Org enumeration (`author=`):** the best yield per request.
- High curation rates: `mercor` 5/10, `harborframework` 6/11, `ScaleAI` 9/33, `SWE-bench` 5/17, `SWE-bench-Live` 3/5, `openai` 5/16, `osunlp` 5/39, `xlangai` 4/39, `microsoft` 10/100.
- Empty or irrelevant: `nvidia` (robotics and training data; the NeMo Gym envs reach HF only through `open-athena/nemotron-gym-*` Harbor conversions), `PrimeIntellect` (RL task pools, mostly SWE mirrors), `open-llm-leaderboard` (results).

**Spaces:**
- `filter=agent-environment` (27) and `filter=openenv` (3,000+) are about 95% hackathon environments from April 2026 (Meta PyTorch OpenEnv hackathon): email triage, code review, customer support. Treat them as a long tail and keep only official `openenv/*` plus anything with ≥5 likes.
- `search=leaderboard&sort=likes`: 2,334 unique, about 22% agent/tool/code/domain related. The top 200 by likes are high-signal pointers to benchmarks.

**Kaggle:**
- Benchmarks: org-owned = high signal. Community: 968 rows, about 2% worth keeping, using a votes ≥ 12 or views ≥ 1,500 cutoff.
- Competitions: 754 total, about 30 LLM/agent-relevant.
- Datasets search: 599 hits across 23 queries, 6 kept (about 1%). Almost all "LLM benchmark" datasets on Kaggle are score tables, not tasks.

## 4. Traps

- **Harbor-tagged ≠ task set.** Of the 195 `harbor` repos, at least 39 (20%, by tag regex; more on manual review) are ATIF trajectories, eval runs or SFT traces (`violetxi/tb2-eval-*`, `*/AgentTrove` forks, `reasoning-degeneration-dev/*`, `laion/*-traces`). Keep a row only if the card or files show `task.toml` or `tests/`, or the tags include `benchmark`/`agent-benchmark`/`rl-environment`, and drop it if the tags include `agent-trajectories`/`atif`/`sft`/`traces`.
- **Gated repos:** 23 of the 250 curated rows are gated (`auto` or `manual`). Their README isn't readable anonymously, so the repo URL, paper and task count come from tags only. An HF token that has accepted the terms would fill these in.
- **Name collisions** need an owner-qualified id. "ClawBench" is used for TIGER web agents, ClawBenchPro and ZClawBench. "FlowBench" is both the 2024 paper and a 2026 HF set. "Web-Bench" is ByteDance's web dev benchmark, while "WebBench" is Halluminate's live-site set. "ACE" is Mercor's.
- **Popularity is inflated by harnesses.** Terminal-Bench and SWE-bench downloads (100k+) are harness pulls, not people. Rank within a domain by likes, or by downloads relative to that domain's median.

## 5. Recommended scheduled crawl

Emit one JSONL row per candidate in this file's schema. Write to `catalog/raw/hub-sources.jsonl` in append-then-dedupe mode. `build.py` already merges on `key(id)`.

**Daily (cheap, high precision, about 30 requests):**
1. HF `datasets?filter=benchmark:official` and `filter=benchmark:eval-yaml`, fully paged.
2. HF `datasets?filter=harbor&sort=lastModified`, pages until `lastModified` < last run.
3. HF `datasets?filter=agents|agent|agent-benchmark|rl-environment|terminal-bench|swe-bench&sort=lastModified`, one page each.
4. Kaggle `ListBenchmarks` (12 pages of 100), diffed on benchmark id.
5. Kaggle `ListCompetitions` with `LIST_OPTION_ACTIVE`.

**Weekly (about 150 requests):**
6. HF `author=` sweep over a watch-list of orgs: harborframework, laude-institute, mercor, ScaleAI, SWE-bench, SWE-bench-Live, nebius, openai, Anthropic, meta-agents-research-environments, facebook, google, microsoft, amazon, AmazonScience, Salesforce, ServiceNow, ServiceNow-AI, sierra-research, xlangai, osunlp, McGill-NLP, TIGER-Lab, allenai, futurehouse, cais, ai-safety-institute, ibm-research, inclusionAI, ByteDance-Seed, bytedance-research, zai-org, Qwen, MiniMaxAI, internlm, InternScience, snorkelai, vals-ai, PatronusAI, galileo-ai, benchflow, datacurve, FineEnvs, open-athena, open-thoughts, laion, birdsql, hkust-nlp, Hcompany, likaixin, agents-last-exam, claw-eval, Genentech, rasynai, SamuelChien821, MathArena, AI-MO.
   - Add an org automatically once it has two curated rows.
7. HF search queries with more than 5% curated yield: `swe-bench, swe, terminal, harbor, agent, web, finance bench, crm, browsecomp, bird, webarena, spreadsheet, mle-bench`, each with `sort=lastModified`, one page.
8. HF Spaces `search=leaderboard&sort=lastModified` and `search=arena&sort=lastModified`, one page each, filtered with the agent regex (§6).

**Monthly:**
9. Domain-word sweep: legal, tax, accounting, insurance, finance, medical, clinical, ehr, chip, verilog, rtl, sql, spreadsheet, excel, cad, ctf, cyber, devops, sre, telco, lean, science, biology, chemistry, materials. Use `sort=lastModified`, one page each, and send the output to the human review queue.
10. Kaggle datasets search: browsecomp, swe-bench, agent benchmark, tool use, arc-agi, gaia. Low yield, but cheap.
11. Refresh signals (`downloads`, `likes`, `lastModified`, `totalTeams`, `viewCount`/`voteCount`) for every existing row using the per-repo endpoints.

**Pipeline per candidate:**
1. List call.
2. Score with the rules in §2. Discard anything under the threshold, and anything whose author is on a denylist: `open-llm-leaderboard`, `open-llm-leaderboard-old`, `mteb`, `Stage-jh-monitor`, `violetxi`, `dougalldeepmind`, `reasoning-degeneration-dev`.
3. Per-repo GET plus README for the survivors. Pull the GitHub/arXiv links and `dataset_info.splits` counts.
4. Classify grading and environment from keywords ("tests/", "pytest", "Docker" → tests/container; "rubric" → rubric; "judge" → llm-judge; "VM", "qcow2", "OSWorld" → vm; "live website" → live-web; "mock", "simulated", "MCP server" → api-sim).
5. Queue for human confirmation when the score is borderline.

**Dedupe rule:**
- Primary key is `build.py`'s `key(id)`: lower-cased alphanumerics, with a trailing `bench`/`benchmark` stripped.
- `id` is the benchmark's canonical short name, never the repo path.
- To collapse mirrors, when two HF repos share the same `key(name)`, keep the one whose owner matches the GitHub org or paper authors, or else the one with the most likes, and put the rest in `notes` as mirrors.
- Version suffixes (`-2`, `-2-1`, `-v2`, `-verified`, `-lite`, `-pro`, `-hard`, `-multilingual`) stay **separate** ids, because they're different task sets.
- Monthly or rolling releases (Monthly-SWEBench-YYYY-MM, SWE-rebench monthly, MathArena per competition) collapse to one id with the latest release in `url_data`.
- Kaggle language variants (MultiLoKo-*, Global-MMLU-Lite-*, MGSM-*) and prompt variants (GPQA few/zero-shot, SciCode sub/main, LiveCodeBench release-vN) collapse into their suite.

**Ranking signal:**
- `score = log1p(likes)*2 + log1p(downloads)*0.5 + recency_bonus(lastModified within 90d) + 3*benchmark:official + 2*harbor-tag`.
- For Kaggle: `log1p(votes)*2 + log1p(views)*0.5` for Benchmarks, and `log1p(totalTeams)` for competitions.
- Rank within domain, not globally.

## 6. The agent regex used for Spaces and Kaggle titles

```
agent|tool|function|swe|terminal|web|browser|gui|computer|osworld|gaia|tau|mcp|sql|spreadsheet|code|coding|research|legal|financ|medical|clinical|cyber|ctf|rtl|verilog|telco|dabstep|enterprise|workflow|harbor|game|chess|mle|kaggle|planning|android|mobile
```

## 7. What auth would add

- **HF token:** unlocks README and file listings for the 23 gated curated repos. That fills in n_tasks, repo and paper for GAIA, OSWorld 2.0, Toolathlon, APEX-Agents, WorkArena, SafeArena, ST-WebAgentBench, Mind2Web-2, Online-Mind2Web, LiveResearchBench, SGI-DeepResearch, BioMysteryBench, DrugDiscoveryBench, mu-bench, SpeedrunBench, HLE, deep-swe, harbor-mix, sciagentarena, OSWorld-Science, Telco challenge and EnterpriseBench. It also raises the rate limit.
- **Kaggle API key:** makes the competition list a stable documented API and adds `competitions files` and leaderboard downloads. It doesn't cover Benchmarks, which still need the internal endpoint.
