# Company-built agent evals: notes (verified 2026-09-24)

`companies.jsonl` has 221 rows (115 full, 65 partial, 41 private), deduplicated from four research passes.

1. Product, fintech and vertical companies.
2. Data vendors, legal and healthcare.
3. Frontier labs and big tech.
4. Prime Intellect and the Environments Hub.

Duplicates were merged, keeping the richer row and appending the other row's notes after "merged:". Where a grading or environment enum was unknown, it is set to mixed or none and the notes say "UNVERIFIED". `harbor_status` is "unknown" everywhere; where Harbor availability is known, the notes say so. The prior-fetch corpus at ~/Desktop/eval-market/raw/corpus/ does not exist on this machine, so every source was fetched fresh.

## Prime Intellect and Environments Hub (pass 4)
- **research-environments** (github.com/PrimeIntellect-ai/research-environments, Apache-2.0)
  - Env categories: code, if, knowledge, lean, long_context, math, multimodal, reasoning, science, search, swe, terminal, tool_use.
  - HARBOR.md plus a root `registry.json` make it a Harbor registry. Two datasets are registered: general-agent@2026-06-25 (4,417 tasks) and tmax@2026-07-01 (14,600 tasks). TMax is by hamishivi/tmax, not a company.
  - It wraps many company benchmarks, which makes it the best source of already-ported tasksets. The wrapped benchmarks:
    - Harvey LAB (Harbor Hub harveyai/lab)
    - Scale MCP-Atlas, SWE-Atlas QnA/RF/TW and DrugDiscoveryBench
    - Snorkel Senior SWE-Bench
    - Mercor APEX-Agents 1.1
    - ServiceNow EnterpriseOps-Gym (649 oracle tasks)
    - DataCurve DeepSWE
    - Databricks OfficeQA-Pro-v2, plus PI's audited 82-task version
    - Sierra tau2 and tau3
    - Kilo PinchBench
- **Environments Hub:** the public API (`https://api.primeintellect.ai/api/v1/environmentshub/?limit=100&offset=N`) lists 1,748 envs.
  - Company teams that publish there: zapier (AutomationBench), handshake-ai (atlas-finance), snorkel-ai (finqa-reasoning), browserbase (filtered WebVoyager/Mind2Web), hud, proximal (FrontierSWE), vibrantlabsai (ITSMBench, ecom-bench, tau2-infinity), tonic-ai, cognida, iceberg, praesidiumsystems, zenml (Harbor-native zenml-bench), benchflow (SkillsBench), intertwine, chakra-labs, human-intuition, theartofservice, standard-data and solar-sight.
  - Most of the small-vertical Hub envs have no public repo; contact them through the Hub team page.
- **Sources:**
  - gh api listing of the research-environments repo, plus its READMEs
  - https://www.primeintellect.ai/blog/frontier-swe
  - https://www.primeintellect.ai/case-study/zapier
  - https://arxiv.org/abs/2604.18934
  - https://github.com/zenml-io/zenml-bench
  - https://github.com/vibrantlabsai/Enterprise-Worlds
  - https://github.com/pinchbench/skill
  - https://blog.kilo.ai/p/kiloclaw-hosted-openclaw


## Part A: company eval inventory, per-company notes (verified 2026-09-24)

46 entries in part_A.jsonl. Where a company has no eval, it says "nothing found".

### Payments / fintech
- **Stripe**: Integration Benchmark, 11 tasks (5 backend, 3 full-stack, 3 gym), MIT, in stripe/ai/benchmarks. Each task has an environment/ folder, a hidden grader/ and a reference solution. Grading uses deterministic API tests, UI tests and Stripe object inspection. Ran on a goose harness with an MCP docs server. Sources: https://stripe.com/blog/can-ai-agents-build-real-stripe-integrations, https://github.com/stripe/ai/tree/main/benchmarks
- **Ramp** (the most eval-active fintech):
  - Ramp SWE-Bench (private, internal backend tasks).
  - Ramp Accounting Bench: 137 tasks, 22 worlds, 92 tools including QuickBooks.
  - APEX-Accounting with Mercor: 160 tasks, closed.
  - Six internal production evals for financial ops.
  - labs.ramp.com is a JS SPA, so details came from search and the page's meta tags.
  - Sources: https://labs.ramp.com/swebench, https://labs.ramp.com/ramp-accounting-bench, https://labs.ramp.com/apex-accounting, https://arxiv.org/abs/2607.27189, https://builders.ramp.com/post/financial-benchmarks
- **Column Tax**: TaxCalcBench, 51 cases in v1, MIT repo; v2 released June 2026. https://github.com/column-tax/tax-calc-bench
- **Daloopa**: FinRetrieval, 500 questions, MIT dataset on HF. https://arxiv.org/abs/2603.04403
- **Rogo**: BigFinanceBench, 928 rubric items; a 50-question subset is on HF. https://rogo.com/news/introducing-the-big-finance-benchmark
- **Plaid / Brex / Mercury / Klarna / Nubank / Intuit**: nothing found.

### Finance data / research
- **Kensho (S&P)**: BizBench, DocFinQA, FIND (gated), BFF-Bench and VERDICTS (human labels for judging LLM judges), all on HF under `kensho/`. The S&P AI Benchmarks leaderboard is being sunset. https://huggingface.co/kensho, https://benchmarks.kensho.com/
- **Hebbia**: Financial Services Benchmark, 600+ workflows (Sept 2025). The judge-consensus methodology is public; the data is not. https://www.hebbia.com/blog/which-model-will-give-me-the-edge
- **AlphaSense**: no published benchmark, only marketing and the Forrester Wave.
- **Bloomberg**: no agent benchmark found. BloombergGPT used internal sentiment/NER eval sets. Its ACL 2026 papers page returned 403.

### Data platforms
- **Databricks**: OfficeQA Full/Pro (246/133), OfficeQA Pro V2 (90), DIBS (Dec 2024, mixes internal and academic sets). https://github.com/databricks/officeqa, https://arxiv.org/abs/2603.08655, https://www.databricks.com/blog/benchmarking-domain-intelligence
- **Snowflake**:
  - Spider 2.0-Snow runs on a Snowflake-hosted evaluation account.
  - Spider 2.0-AIFunc: 465 instances, Snowflake AI Research.
  - AvalancheBench (Anupam Datta's group).
  - DARE-Bench and HyDRA-Bench on HF.
  - Agent GPA judge framework, validated on a private Snowflake Intelligence set.
  - Cortex Agent Evaluations is a product feature, not a benchmark.

### Coding-agent companies
- **Cursor**: CursorBench, private tasks mined via Cursor Blame, graded by agents. v4.0 public leaderboard since 2026-09-10. https://cursor.com/blog/cursorbench, https://epoch.ai/benchmarks/cursorbench
- **Cognition**: cognition-golden, private, with train/test splits and evaluator agents. https://cognition.com/blog/evaluating-coding-agents
- **Sourcegraph**: CodeScaleBench, 370 tasks, Apache-2.0, Docker. codeprobe mines tasks from PRs. https://github.com/sourcegraph/CodeScaleBench
- **Replit**:
  - ViBench: PRD-to-app, graded by a Playwright eval agent. Called "public" and CC-BY-4.0, but no repo found.
  - replit/agent-challenge: small, from 2024.
  - Sources: https://replit.com/blog/evaluating-and-improving-agent-at-scale, https://vibench.ai/
- **Vercel**: next-evals-oss (MIT, shown on nextjs.org/evals); DeepsecBench (secret codebase, 231 findings); internal v0 eval sets.
- **GitHub/Microsoft**:
  - CheckpointBench, from real Copilot sessions.
  - Win-Hill, for Windows containers.
  - About 100 containerized repos.
  - MCP server tool-selection offline eval.
  - All private.
  - Microsoft Excel Agent Mode reports on SpreadsheetBench, which Microsoft did not build.

### Workflow / SaaS
- **Zapier**: AutomationBench. 600 public tasks plus 200 simple ones; the official score uses a private held-out set. End-state assertions, 47 simulated SaaS apps. Also on the Prime Intellect Env Hub. https://github.com/zapier/AutomationBench, https://arxiv.org/abs/2604.18934
- **Box**: Complex Work Eval, proprietary. Weighted rubric, 11–12 industries. Box publishes a blog post for each frontier model launch.
- **Notion**: internal evals in Braintrust (vendor case study only).
- **Airtable, Linear**: nothing found beyond architecture posts.
- **Shopify**: Sidekick GTX sets, a calibrated LLM judge and a merchant simulator. All private. https://shopify.engineering/building-production-ready-agentic-systems
- **Datadog**:
  - Bits AI SRE eval platform: private, replays incidents from world-snapshots.
  - BOOM: public forecasting benchmark, not an agent benchmark.
  - Sources: https://www.datadoghq.com/blog/engineering/bits-ai-eval-platform/

### Customer service
- **Intercom**: Fin Apex resolution-rate claims (73.1%). No offline dataset has been published. fin.ai/benchmarks is industry KPIs, not tasks.
- **Sierra**: tau-bench and tau2-bench (MIT), plus mu-Bench (ASR).
- **Decagon**: eval-engine blog only.

### Adjacent enterprise (discovered)
- **Salesforce**: CRMArena-Pro (4,280 instances, CC-BY-NC) and SCUBA.
- **ServiceNow**: WorkArena and WorkArena++.

### Insurance
- **Lemonade, Sixfold, EXL**: no agent benchmarks. Sixfold's "AI Accuracy Validator" is a product; EXL gives only vendor accuracy claims.
- **UNDERWRITE** (arXiv 2602.00456) is the only insurance agent benchmark found. The authors appear to be Snorkel AI; this is not verified.

### Logistics
- **Flexport**: no benchmark.
- **ATLAS** (HTS customs classification) is by **Flexify.AI**, not Flexport. https://arxiv.org/abs/2509.18400

### Out of scope but seen
BankerToolBench, Finance Agent Benchmark (Vals), ICBCBench, Herculean, and Meta's REAP/"ProdCodeBench" (arXiv 2604.01527). These are lab, academic or vendor work, so they are not recorded here.

## Part B: company-built agent evals (verified 2026-09-24)

85 rows in part_B.jsonl. Counts come from HF cards, the GitHub API, repo trees, or the vendor pages listed under each company. Anything that isn't confirmed is marked UNVERIFIED in the row notes.

### Mercor
Mercor runs the APEX family with a live leaderboard at mercor.com/apex. The line covers APEX-v1-extended (400 held-out + 100 dev), APEX-Agents (480 tasks, 33 worlds, harness `Mercor-Intelligence/archipelago`), APEX-Agents 1.1 (240 tasks, on Harbor Hub `mercor/apex-agents-1-1`), APEX-SWE (50 public tasks), APEX-Accounting (built with Ramp: 160 closed tasks + a 10-task dev set in Harbor form on HF `mercor/apex-accounting-harbor` and on Harbor Hub) and ACE. Mercor also publishes Harbor+SkyRL training recipes and eval traces, and bought Sepal AI (SheetBench co-author) in Feb 2026.
Sources: mercor.com/blog/introducing-apex-agents-1-1/, the HF READMEs for mercor/*, gh org Mercor-Intelligence, arxiv 2601.14242.

### Sierra
Sierra's evals are tau-bench (165), tau2-bench (airline 50 / retail 114 / telecom 2285 pool), τ³ banking_knowledge (97) and τ-Voice, all in the tau2-bench repo, with the leaderboard at taubench.com. Two newer repos: **hyper-tau-bench (τ^τ)**, where a coding agent *builds* the customer-service agent and is scored by that agent's τ³ pass rate, and **mu-bench** (STT, 4,270 utterances).
Sources: gh sierra-research/* READMEs, the raw tasks.json files.

### Scale AI
The SEAL lab now lives at labs.scale.com/leaderboard, with 25 boards. Agentic sets in the JSONL: SWE-Bench Pro V2 (642 / hard 51 / v1 731), MCP-Atlas (500 public), SWE Atlas QnA/TW/RF (124/90/70, Harbor format), SWE-Interact (75, Harbor), DrugDiscoveryBench (82, Harbor, with Phylo), RLI (240, with CAIS; 10 public), PropensityBench (979), HiL-Bench (200), LHAW (285), RSI Bench (4 samples, Harbor+Modal GPUs), CliniCARE-Bench (750 Harbor tasks over MIMIC-IV) and ResearchRubrics. Also recorded: MultiChallenge, VisualToolBench, PRBench, HLE. Scale's newer releases (SWE-Atlas, SWE-Interact, DDB, RSI, CliniCARE) all ship in Harbor format.
Sources: labs.scale.com/leaderboard, gh scaleapi/*, HF ScaleAI/*, scale.com/blog/rli, scale.com/blog/hil.

### Surge AI
Surge publishes the Tuesday Work Index at surgehq.ai/benchmarks. The agentic sets are DAYJOB Healthcare (50) and Finance (80), both Harbor format and MIT-licensed on HF, plus HANDBOOK.md (5 enterprise domains, with per-task mutated handbooks) and EnterpriseBench/CoreCraft (150 tasks, paper only). GDP.pdf (100) runs on Inspect. Chartography, AdvancedIF and Hemingway-bench are non-agentic and were left out.
Sources: surgehq.ai/benchmarks, gh surge-ai/{dayjob,handbook,gdp-pdf}, HF surgeai/*.

### Snorkel AI
Snorkel's own sets: Senior SWE-Bench (50 public + 50 private, Harbor Hub), Agentic Coding (100, private), SnorkelUnderwrite and SnorkelFinance (HF traces). It also hosts leaderboards for grant/partner benchmarks: Continual Learning Bench, SlopCodeBench, Agents' Last Exam (Berkeley RDI, 1,500+ tasks, 147 public), Terminal-Bench and OSWorld 2.0.
Sources: snorkel.ai/leaderboard/, senior-swe-bench.snorkel.ai, snorkel.ai/blog/introducing-the-snorkel-agentic-coding-benchmark/.

### Vals AI
Vals has the largest domain catalogue, at vals.ai/benchmarks. Harnesses are public on GitHub while scored sets stay private: finance-agent (v1: 537 Qs on HF), finance-agent-v2, legal-research-bench, tax-agent-bench, emb-public-dataset, code-migration-public, proof-bench and the Vibe Code Bench scaffold. Its infrastructure is called "Valkyrie" / benchmark-runtime. Vals also runs Harvey LAB as a leaderboard and publishes VLAIR, which compares legal *products* against lawyers. Other proprietary sets: CorpFin v2, TaxEval v2, MortgageTax, CaseLaw v2, MedCode, MedScribe, Public Benefits Bench (SNAP), CyberBench, SRE Bench, BioMysteryBench and CUA-bench/KSP. I recorded the domain ones.

### Harvey
Harvey has two sets. LAB (harveyai/harvey-labs, MIT) has a README badge of 1,671 tasks, 984 task.json files in the tree, and the launch blog said 1,200+ tasks and 75k criteria; the Harbor Hub entry harveyai/lab comes from the caller's hint. BigLaw Bench (harveyai/biglaw-bench) has samples only: core, retrieval and workflows.
Sources: harvey.ai/blog/introducing-harveys-legal-agent-benchmark, the gh READMEs.

### Handshake AI
Handshake's ATLAS suite includes BankerToolBench (100, arxiv 2604.11304), ATLAS-Finance (100 tasks in 13 firm worlds, Harbor format) and VIALS. Handshake also open-sourced gandalf-the-grader (agent-as-judge), keeps a Harbor fork, and published a DeepSWE reward-hacking analysis.
Sources: gh Handshake-AI-Research, joinhandshake.com/research/benchmarks/articles/atlas-finance-...

### Datacurve
DeepSWE has 113 Harbor tasks (confirmed by counting task.toml files) across 91 repos. v1.1 uses Pier, Datacurve's Harbor fork for air-gapped CLI agents, with a separate verifier environment.
Sources: gh datacurve-ai/deep-swe, deepswe.datacurve.ai/blog/deepswe-v1-1.

### Patronus AI
Patronus has FinanceBench (150 open), TRAIL (148 traces), MEMTRACK, BLUR (gated) and SpeedrunBench (gated). Its commercial line is now private "Generative Simulators" / Digital World Models.
Sources: gh patronus-ai, HF PatronusAI, patronus.ai/blog/memtrack.

### Turing
Turing has SWE-Bench++ (500 public, arxiv 2512.17419) and CRAVE (1,200 code-review verdicts). Its other HF packs are sales samples.

### HUD
HUD built SheetBench-50 with Sepal AI and now runs it as a HUD v6 taskset. AssembleBench is robotics. HUD also rehosts OSWorld-Verified/Gold, SpreadSheetBench and Online-Mind2Web as tasksets, and its org has many env templates (gdpval-template, sdlc-template, cybergym handoff). The hud.ai/leaderboards page rendered empty.

### Toloka
Toloka has no public task set. It offers a private τ-bench extension dataset and AI Arena (pass^5). tolokaforge is its open harness, with 7 coding-CLI modes and deterministic grading.

### AfterQuery (new vendor found) / Legora
AfterQuery publishes FinanceQA, VADER, App-Bench, IDE-Bench, UI-Bench, Market-Bench and MCP-Universe (HF), and co-built Legora BAR and SpreadsheetBench 2. Legora BAR is private: 5,161 cases, run inside Legora's own harness, with one public tax case at legora-oss/legora-bar-tax-case.
Sources: afterquery.com/research, legora.com/bar.

### Labelbox
Labelbox has a private, expert-graded Deep Research Agents leaderboard.

### Thomson Reuters
TR has CoCounsel Bench (CoCoBench), an internal release gate. The Medium post returned a 403 when fetched, so the details come from search snippets.

### Healthcare
- Microsoft SDBench: 304 NEJM cases, unreleased.
- Hippocratic RWE-LLM: 307k calls reviewed by clinicians. It is a process, not a task set.
- Abridge: internal ASR/note evals.
- Ambience: ICD-10 coding study.
- Epic, Nabla, OpenEvidence: no named agent eval set found.

### No public agent eval set found
- Fleet: private enterprise-software gyms for labs. Contact angle: sales/research.
- Invisible: sells eval infrastructure but has no named benchmark.
- micro1: the search hit, "micro1-agent-benchmark", is a student repo, not micro1's.
- LexisNexis, Clio, EvenUp: their "benchmark" reports are about law-firm operations, not AI agents.
- UK AISI / GSA: skipped (government).

### Other vendors worth a follow-up
Deeptune (acquired Jul 2026), Mechanize, Sepal AI (now Mercor) and Phylo (DDB partner).

## Part C: industry-lab agent evals, notes by org (checked 2026-09-24)

Method: GitHub repos checked with `gh api repos/...`, HF datasets with `curl huggingface.co/api/datasets/...`, arXiv IDs checked against arxiv.org/abs citation_title, plus WebSearch/WebFetch. Counts marked UNVERIFIED in the JSONL came from memory or secondary sources.

### OpenAI
- Preparedness evals are published in **openai/frontier-evals** (openai/preparedness redirects there): project/{paperbench, swelancer, evmbench}. MLE-bench is its own repo. BrowseComp and HealthBench ship through openai/simple-evals.
- 2025-26 releases: GDPval (220 gold / 1,320 full; HF openai/gdpval), EVMbench (Feb 2026, with Paradigm; paradigmxyz/evmbench), FrontierScience (Dec 2025; HF openai/frontierscience, 160 gold), BrowseComp Long Context (HF).
- Internal/private: the AI self-improvement evals in the system cards (OpenAI PRs, OpenAI-Proof Q&A). Not released.
- Sources: openai.com/index/gdpval/, openai.com/index/introducing-evmbench/, openai.com/index/frontierscience/, openai.com/index/introducing-swe-bench-verified/, arxiv 2510.04374, 2502.12115, 2504.01848, 2410.07095, 2504.12516, 2505.08775, 2601.21165.

### Anthropic
- Anthropic publishes its safety evals, not capability benchmarks. Public: agentic-misalignment (anthropic-experimental), SHADE-Arena (safety-research, partial), Petri (Oct 2025; **donated to Meridian Labs May 2026 as inspect_petri / Petri 3.0**), Bloom (Dec 2025), and the original performance take-home (Jan 2026, 4.1k stars).
- Capability evals are private. The engineering blog covers method: "Demystifying evals for AI agents" and "Quantifying infrastructure noise in agentic coding evals" (Terminal-Bench 2.0 moved 6pp across resource configs).
- Sources: anthropic.com/engineering/infrastructure-noise, anthropic.com/engineering/demystifying-evals-for-ai-agents, meridianlabs.ai/blog/posts/introducing-petri-3/, itbrief/winbuzzer coverage of the donation.

### Google / DeepMind
- deepmind.google/research/evals lists these agentic evals: DeepSearchQA (900 prompts, HF google/deepsearchqa, Kaggle leaderboard) and ASIMOV-Agentic-v1 (HF google/asimov_agentic, robotics safety). The rest of that page (FACTS, SimpleQA Verified, MRCR) is not agentic.
- Dangerous-capability evals (in-house CTF, self-proliferation, stealth) are partly public through google-deepmind/dangerous-capability-evaluations and inspect_evals gdm_*.
- Google Research: AndroidWorld. Its budget-aware-agent repo (COLM 2026) evaluates on BrowseComp; it is a method, not a benchmark.
- No DeepMind-owned public computer-use task set found. Gemini computer-use results are reported on third-party benchmarks.

### Salesforce AI Research
- Most prolific company publisher: CRMArena, CRMArena-Pro (same repo, HF CC-BY-NC), MCP-Universe (Apache), SCUBA (computer use on the Salesforce platform, 300 tasks), LoCoBench / LoCoBench-Agent, MCPEval (framework). APIGen-MT-5k is training data and is left out of the JSONL.
- Their "2026 benchmark" press releases (Connectivity Benchmark, Agentic Enterprise Index) are surveys, not evals.

### ServiceNow
- NOWAI-Bench (github ServiceNow/NOWAI-Bench, Apr 2026) is the umbrella portfolio. It currently holds EnterpriseOps-Gym (1,150 tasks; HF oracle config = 649 across 8 domains, plus +5/+10/+15 distractor-tool configs; Artificial Analysis runs EnterpriseOps-Gym-AA) and EVA-Bench (voice agents, ServiceNow/eva).
- Older work: WorkArena (33 atomic tasks / 19,912 instances), WorkArena++ (682), BrowserGym + AgentLab (harness framework, a competitor to Harbor).

### IBM Research
- HF collection "ibm-research/enterprise-agents-and-benchmarks" contains ITBench (now itbench-hub/ITBench, plus ITBench-Lite and Trajectories), AssetOpsBench (460+ scenarios, IJCAI 2026 competition), VAKRA (tool-calling), ScarfBench (Java framework migration, 102 apps, 1,331 tests), CUGA agent.
- ST-WebAgentBench (ICLR 2026). ITBench-AA with Artificial Analysis (May 2026, 59 SRE tasks, every model below 50%).

### Microsoft
- Windows Agent Arena, SWE-bench-Live (MultiLang split: 1,077 instances on 2026-08-21), STATE-Bench (May 2026, 450 tasks, memory), SentinelBench (Jun 2026, microsoft/sentinel_environments, 100 scenarios, monitoring agents).
- SDBench (304 NEJM cases) is private: Microsoft calls it a "research demonstration". No MAI-DxO repo found.

### Amazon / AWS
- SWE-PolyBench (2,110), SOP-Bench (KDD 2026, 2,000+ tasks, 12 domains), PatientAgentBench (Jul 2026), **aws-bench** (Jul 2026, github aws-bench/aws-bench + aws-bench-datasets, 134 tasks, **built on Harbor**, runs against live isolated AWS accounts).
- AgentCore Evaluations is a product, not a task set.
- Sources: amazon.science/blog/sop-bench-..., infoq.com/news/2026/08/aws-bench-agent-evaluation/.

### Meta
- ARE platform + Gaia2 (1,120 scenarios, 800 public validation; HF CC-BY-4.0; arxiv 2602.11964 / 2509.17158). GAIA is co-owned with HF (gated). MLGym. OpenEnv (now under huggingface/OpenEnv; meta-pytorch/OpenEnv redirects).

### NVIDIA
- CVDP (Verilog/RTL, has an agentic Docker track) and ProfBench (40 rubric tasks, arxiv 2510.18941). Nemotron reports use third-party sets (Terminal-Bench 2, tau2, BFCL v4). Nemotron-RL-Agentic-Terminal-Pivot is RL training data, not an eval.

### Apple
- ToolSandbox (repo moved to apple-aiml-research/ToolSandbox). AppWorld is Stony Brook NLP, not Apple.

### Alibaba / Qwen
- DeepPlanning (Jan 2026, HF Qwen/DeepPlanning, leaderboard in Qwen-Agent docs). Tongyi DeepResearch (Alibaba-NLP/DeepResearch; Alibaba-NLP/WebAgent redirects there) is an agent. Its WebWalkerQA and similar sets were not added.

### ByteDance Seed
- Multi-SWE-bench (multi-swe-bench org; HF ByteDance-Seed), DAComp (ICLR 2026), WideSearch, EdgeBench (Jun 2026, 134 tasks, scaling law in interaction time).

### Zhipu / Z.ai
- CC-Bench V1.1: 260 trajectory rows on HF, run in Claude Code, human-judged. The environments are not released. AgentBench comes from the THUDM (Tsinghua) lineage.

### MiniMax
- OctoCodingBench (Jan 2026, MIT, Docker envs) and VIBE (full-stack apps, Agent-as-a-Verifier). Both use Claude Code as scaffold or verifier.

### Moonshot, DeepSeek, xAI, Mistral, Cohere, AI21
- None of these orgs has published an agentic task set of its own. They report on third-party benchmarks only (Terminal-Bench, SWE-bench Pro, BrowseComp, GDPval-AA, MCPAtlas, Tool-Decathlon). mistralai/mistral-evals exists (2024, not agentic). Kimi-Researcher is a tech report. Moonshot is recorded as private in the JSONL. The others have no entries.

### Hugging Face
- ScreenSuite (a GUI suite that wraps existing sets), OpenEnv, GAIA co-owner, Gaia2 leaderboard space.

### Allen AI
- AstaBench (ICLR 2026 oral, 2.4K+ problems, Inspect-based, spring-2026 update), DiscoveryWorld, ScienceWorld.

### Sakana
- ALE-Bench (40 AHC problems; code Apache, data CC-BY-ND).

### Epoch AI / METR / Apollo
- MirrorCode (Epoch + METR, 25 programs, Apr 2026; arxiv 2606.30182). METR Time Horizon 1.1 suite (228 tasks, partly public: METR/public-tasks, METR/hcast-public). RE-Bench. Epoch also launched FrontierMath Erdos (Lean; not agentic, not added).
- Apollo: the in-context scheming evals (arxiv 2412.04984) are mostly private and used in lab system cards. The insider-trading env is public.

### Cross-cutting
- Artificial Analysis now runs "-AA" versions of company benchmarks (GDPval-AA, EnterpriseOps-Gym-AA, ITBench-AA). It is becoming the default third-party runner for company-built enterprise evals.
- inspect_evals (UK AISI) already ports agentic_misalignment, browse_comp, gaia, gdm_*, healthbench, mle_bench, paperbench, swe_lancer.
- Arxiv 2609.04298, "Harbor Adapters and Harbor-Index", came up in search. It is worth reading for harbor_status.
