# Long-tail agent benchmark sweep: method

Run on 2026-09-24. Output: `longtail.jsonl`, 359 entries, every one with `verified: 2026-09-24` and `harbor_status: unknown`.

## Sources and yield

| Source | How it was queried | Raw hits | Kept | Notes |
|---|---|---|---|---|
| arXiv API (`export.arxiv.org/api/query`) | `all:agent AND all:benchmark AND (<domain term>)`, sorted by submission date, 25 per query, 2025-01-01 onward. 139 domain queries (legal, EHR, Verilog, GIS, PLC, SCADA, BIM, WCAG, 5G, Godot, COBOL, Korean, nutrition, ...) | 2,317 records, 1,748 unique papers | 252 | Best source by far. Titles with bench/gym/arena/environment were read by hand and chosen for domain spread over fame. Full abstracts were then pulled in batches of 40 with `id_list` to extract repo links and task counts |
| GitHub search on repo names (`gh search repos "<benchmark name>"`) | Run for each chosen paper whose abstract had no repo link (180 names) | 107 candidate repos | 76 attached | Each candidate's README was checked for the arXiv id. 38 matched on the id, the rest on name only (flagged in `notes`). 30 false positives were rejected by hand |
| GitHub topic search | Topics: agent-benchmark, llm-benchmark, agentic-evaluation, terminal-bench, harbor, agent-evaluation, llm-evaluation, benchmark; repos created 2025 or later | 435 | ~40 | Mostly eval frameworks and observability tools. The finds are small company or individual benchmarks that arXiv never sees (Edge Delta SRE benches, Prosus vending-bench, AMD AgentKernelArena, Column Tax) |
| GitHub keyword search, short domain phrases (e.g. "insurance benchmark", "verilog benchmark") | 55 queries, `--created >2025-01-01` | 291 | ~30 | Very noisy: hardware perf benchmarks, CIS Kubernetes hardening, student projects. Still the only place that surfaced the individual-built CAD, RTL, accounting and tax repos. Multi-word queries such as "legal agent benchmark" returned almost nothing |
| UK AISI `inspect_evals` (`src/inspect_evals/`, 137 dirs) | Directory listing plus README of every obscure-looking eval | 137 | 19 | Well-known evals were skipped. Kept: CTI-REALM, Pre-Flight (aviation), UCCB (Uganda), scBench, 3CB, VimGolf, ComputeEval, AgentThreatBench (OWASP agentic), CodeIPI, ANIMA, MORU, PersistBench, b3, Frontier-CS, MLRC-Bench, MaCBench, SOSBench, SEvenLLM, InstrumentalEval |
| Government / nonprofit repos | UKGovernmentBEIS/control-arena, inspect_cyber, METR/public-tasks | 3 | 3 | Guessed NIST and Epoch repo paths returned 404. Nothing found there |
| WebSearch | About 12 targeted domain queries (tax, PLC, BIM, firmware, WCAG, MRO, localization, public sector, Vals) | ~90 results | ~15 | Good precision for niche domains (BIM-Edit, IFCMemoryBench, Embedded Arena, Agents4PLC, ESBMC-PLC suite, CAMB, DiagnosticIQ, AssetOpsBench). The session's shared search budget ran out partway through |
| Awesome lists (dataanswer/awesome-agent-benchmarks, benchflow-ai/awesome-evals) | README scan | ~130 | 0 new | Dominated by 2023–2024 famous benchmarks (WebArena, AndroidWorld, OSWorld, ...) |
| benchmark-radar (ktwu01/benchmark-radar, data zip) | Downloaded the release `benchmark-radar-data.zip` | 1,284 scored benchmarks | 0 | The zip only holds benchmarks that have model scores, which are mostly famous. The site says it tracks 17k+ records from 37 sources, so the full feed may be worth a later look |
| Hugging Face / Kaggle | Not swept (handed to the hub-sources agent partway through) | — | — | No yield measurement taken |

## Field conventions and caveats

- **Owner.** `owner_org` is the GitHub owner of the attached repo. It is null when no repo was found, because the arXiv API does not return affiliations. `owner_type` defaults to `academic` for arXiv papers and is set to `company` for a known list of corporate GitHub orgs (microsoft, nvidia, oracle-samples, QwenLM, latchbio, FujitsuResearch, Handshake-AI-Research, ...).
- **`n_tasks` for arXiv entries.** Taken automatically as the largest "N tasks/instances/scenarios/questions" count in the abstract. Each such entry says so in `notes`. Some are dataset sizes, not task counts (e.g. ReCoQA 29,270; RealCADBench 12,632).
- **`grading` and `environment` for arXiv entries.** Keyword heuristics over the full abstract. 115 entries whose abstract names no grading method are set to `mixed`, and their `notes` say "Grading method not stated in abstract". `environment=api-sim` is loose: it fires on tool / simulation / environment wording.
- **`public`.** `full` when a repo was found. `private` means no code or data link turned up in the abstract or in GitHub search on 2026-09-24. Some of these will publish later, so re-check.
- **`license`.** Taken from the GitHub API when a repo was found, otherwise null.
- **`notes`.** arXiv entries start with the opening of the abstract, cut to about 260 characters.
- **Deduplication.** Where an arXiv paper and a manual entry describe the same benchmark, the manual entry wins (CTI-REALM, GBQA, BixBench, DataClawEval). Two different papers share the name "ERPBench"; they are stored as `erpbench-gair` and `erpbench-cua`.
- **Deliberately left out.** Famous sets: SWE-bench, GAIA, tau-bench, WebArena, OSWorld, MLE-bench, Spider 2.0.

## What to crawl automatically, on a schedule

Ranked by long-tail yield per unit of effort:

1. **arXiv API, daily, `sortBy=submittedDate`.** Query `all:agent AND all:benchmark AND <domain>` for about 140 domain terms, or better, `cat:cs.AI OR cs.CL OR cs.SE` with `ti:(bench OR gym OR arena)` over the last day. Rate limits: use https, about 6 s between calls, and back off 30 s or more on HTTP 429 (http:// now returns 301, and bursts return 429). Pull full abstracts with `id_list` in batches of 40. Roughly 15% of benchmark-titled papers are domain-specific and new.
2. **GitHub name resolution for each new arXiv benchmark.** Search the name, then confirm the repo's README contains the arXiv id. That check is cheap and removes most false positives. Only about half of papers put the repo link in the abstract; the arXiv `comment` field adds a few more.
3. **UK AISI `inspect_evals`, weekly diff of `src/inspect_evals/`.** Small but high quality. Every addition is already runnable, often contributed by the benchmark's authors or a company (Airside Labs, Lakera, LatchBio, NVIDIA, Microsoft). It grew to 137 evals.
4. **GitHub topic feeds (`terminal-bench`, `harbor`, `agent-benchmark`), weekly, `created:>last-run`.** Catches company and individual benchmarks that never reach arXiv. Many `terminal-bench`/`harbor` repos are single tasks or adapters (e.g. `ssslakter/nyuctf-adapter`), and those convert directly.
5. **benchmark-radar.org full feed.** Only if the full 17k-record feed can be pulled; the public zip is score-centric.
6. **Low value:** awesome lists (stale, famous-heavy) and GitHub free-text keyword search (under 10% precision).

## Queries that returned nothing and gaps that remain

"all:contract AND all:law", "human resources", SCADA, "IEC 61131", mainframe, "African languages", veterinary and "lab protocol" returned no 2025+ agent benchmark papers on arXiv. The thinnest domains in the output:

- HR/recruiting: 1 entry (PeopleSearchBench)
- government/civic: 2
- real estate: 2
- embedded firmware: 2
- accessibility: 3
- aviation MRO: only the CAMB knowledge set

These gaps need targeted web search or vendor pages, which this run could not finish because the search budget ran out.
