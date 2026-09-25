# catalog — every agent eval task set we can find, and whether it runs in Harbor form

The index behind "find the right test for your agent": one row per benchmark, from the famous ones labs put in model
cards down to the 100-task set a solar-quoting startup built for itself. Each row says who owns it, what domain it
tests, how it is graded, what environment it needs, whether it is public, and whether a Harbor dataset for it exists
yet — so the gap between *indexed* and *runnable here* is a column, not a guess.

    python3 catalog/build.py        merge raw/*.jsonl into index.jsonl and print the tally

## What is in it (2026-09-24)

1,065 benchmarks. 83 already have a Harbor dataset, 779 are public or partly public and not yet converted, 203 are
private (a company's internal suite — a contact, not a download).

| file | what | rows |
|---|---|---|
| `raw/model-cards.jsonl` | every benchmark in the eval tables of 31 model releases (GLM 5.3 → Opus 5.5, GPT-6, Qwen 3.8, DeepSeek V4, Kimi K3, MiniMax M3, …); `cited_by` lists the models | 194 |
| `raw/companies.jsonl` | evals companies built for their own domain — Stripe, Ramp, Zapier, Sierra, Mercor, Scale, Harvey, Vals, Intercom, … — public, partial or private | 221 |
| `raw/longtail.jsonl` | obscure domain benchmarks, 2025–2026: PLC code, power grids, BIM edits, telecom, tax returns, EHR, aviation | 359 |
| `raw/hub-sources.jsonl` | Hugging Face datasets and Spaces, Kaggle Benchmarks and competitions, with usage signals (`signals`) | 399 |
| `raw/harbor-coverage.jsonl` | what already exists as a Harbor dataset: the Hub (317 packages), legacy `registry.json`, the local corpus | 358 |

Research notes, with the sources each sweep actually read: `raw/*-sources.md`, `raw/*-notes.md`, `raw/*-method.md`,
`raw/hub-sources-crawl.md` (the scheduled-crawl spec), `raw/conversion.md` (how each source shape becomes a Harbor
task, and the QA gates).

## A row

| field | |
|---|---|
| `id`, `name`, `owner_org`, `owner_type` | `owner_type`: lab, company, academic, individual, community, government |
| `domain` | one of ~28 fixed facets (`swe`, `finance`, `healthcare`, `chip-hardware`, `engineering-industrial`, …) mapped by `DOMAINS` in build.py; `domain_raw` keeps what the sweep wrote |
| `task_kind`, `n_tasks` | |
| `url_repo`, `url_paper`, `url_data`, `license` | null when not found — never guessed |
| `grading` | tests, exact-match, state-check, llm-judge, rubric, human, mixed |
| `environment` | container, multi-container, api-sim, live-web, vm, none |
| `public` | full, partial, private |
| `harbor_status` | `in-harbor` (with `harbor.harbor_dataset`, the canonical package, and `harbor.variants`), `to-convert`, `private` |
| `cited_by`, `found_in`, `signals` | which models cite it, which sweeps found it, HF downloads / likes / Kaggle entrants |
| `notes`, `verified` | anything a sweep could not confirm from a primary source says **unverified** here |

## Known weaknesses

* **`in-harbor` is undercounted.** Prime Intellect's `research-environments` repo is itself a Harbor registry, and HF
  has ~195 repos tagged `harbor`; neither is in `harbor-coverage.jsonl` yet.
* **Long-tail arXiv rows are machine-filled** from abstracts: grading `mixed` means "abstract didn't say", `n_tasks`
  is the largest number in the abstract, and name-only repo matches say "verify".
* **94 model-card rows carry an unverified field**, mostly task counts.
* Joins are by normalised name plus Harbor aliases; two names for one benchmark that share neither still split.

## Crawling it again

The sources that paid, ranked by yield, and how to hit them: `raw/longtail-method.md` (arXiv API, GitHub
name-lookup of new papers, `inspect_evals` weekly diff, GitHub topics) and `raw/hub-sources-crawl.md` (HF
`benchmark:official` / `eval-yaml` / `harbor` / `agents` tag feeds, org watch-list, Kaggle's anonymous
`ListBenchmarks` RPC). Prime's Environments Hub lists everything at
`api.primeintellect.ai/api/v1/environmentshub/?limit=100&offset=N` (1,748 envs).
