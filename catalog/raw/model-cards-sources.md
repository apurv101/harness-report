# Model-card sources (verified 2026-09-24)

Every URL below was fetched and read during this sweep (Hugging Face raw README, rendered page text, system-card PDF, or benchmark image). Benchmark names are listed as they appeared in each source. Rows that only appear in footnotes or body text are marked. Static base-model rows (AGIEval, MMLU-Pro base, etc.) are listed but were not all put in the catalog; see the notes at the end.

Could not read: https://z.ai/blog/glm-5.3 (JS-rendered, returned an empty shell). openai.com pages return 403 to curl/WebFetch, so they were read through a real browser.

## GLM-5.3
- https://huggingface.co/zai-org/GLM-5.3

Benchmarks as cited: Terminal Bench 2.1; Terminal Bench 3.0; DeepSWE (v1.1); NL2Repo; ProgramBench (Almost Solved); FrontierSWE; SWE-Marathon (v1.1); PostTrainBench; CyberGym; ExploitGym (2h / 6h); ExploitBench; Toolathlon Verified; AutomationBench (v1.0.6); Agents' Last Exam (ALE-CLI); HLE w/ Tools; GDPval-AA v2

## GLM-5.3-Flash
- https://huggingface.co/zai-org/GLM-5.3-Flash
- https://raw.githubusercontent.com/zai-org/GLM-5/refs/heads/main/resources/bench_53.png

Benchmarks as cited: Terminal Bench 2.1; DeepSWE v1.1; Agents' Last Exam; AutomationBench v1.0.6; HLE w/ Tools; GDPVal-AA v2; NL2Repo (footnote); Toolathlon Verified (footnote); BabyVision (footnote)

## GLM-5.2
- https://huggingface.co/zai-org/GLM-5.2

Benchmarks as cited: HLE; HLE (w/ Tools); CritPt; AIME 2026; HMMT Nov. 2025; HMMT Feb. 2026; IMOAnswerBench; GPQA-Diamond; SWE-bench Pro; NL2Repo; DeepSWE; ProgramBench; Terminal Bench 2.1 (Terminus-2); Terminal Bench 2.1 (Best Reported Harness); FrontierSWE (Dominance); PostTrainBench; SWE-Marathon; MCP-Atlas (Public Set); Tool-Decathlon

## GLM-5.1
- https://huggingface.co/zai-org/GLM-5.1

Benchmarks as cited: HLE; HLE (w/ Tools); AIME 2026; HMMT Nov. 2025; HMMT Feb. 2026; IMOAnswerBench; GPQA-Diamond; SWE-Bench Pro; NL2Repo; Terminal-Bench 2.0 (Terminus-2); Terminal-Bench 2.0 (Best self-reported); CyberGym; BrowseComp; BrowseComp (w/ Context Manage); τ³-Bench; MCP-Atlas (Public Set); Tool-Decathlon; Vending Bench 2

## GLM-5
- https://huggingface.co/zai-org/GLM-5

Benchmarks as cited: HLE; HLE (w/ Tools); AIME 2026 I; HMMT Nov. 2025; IMOAnswerBench; GPQA-Diamond; SWE-bench Verified; SWE-bench Multilingual; Terminal-Bench 2.0 (Terminus 2); Terminal-Bench 2.0 (Claude Code); CyberGym; BrowseComp; BrowseComp (w/ Context Manage); BrowseComp-Zh; τ²-Bench; MCP-Atlas (Public Set); Tool-Decathlon; Vending Bench 2

## Qwen3.8-Max
- https://huggingface.co/Qwen/Qwen3.8-2.4T-A95B

Benchmarks as cited: Terminal Bench 2.1; SWE-bench Pro; DeepSWE 1.1; NL2Repo-Bench; FrontierSWE; MLS-Bench-Lite; PaperBench; AndroidBench; QwenSWEBench; QwenQoderBench; QwenReactBench; QwenSVGBench; CoWorkBench; WorkSpaceBench; JobBench; SkillsBench; Agents' Last Exam (Pass / Score); Automation-Bench (Pass@1); Toolathlon Verified (Pass@1); WideSearch; HLE w/ tools; GPQA Diamond; HLE; IFBench; $OneMillion-Bench (expert score); HealthBench; PLawBench; PRBench-Legal; PRBench-Finance; MRCR v2 256K (8-needle); LongBench v2

## Qwen3.8-27B
- https://huggingface.co/Qwen/Qwen3.8-27B

Benchmarks as cited: Terminal Bench 2.1 (Terminus); SWE-bench Pro; NL2Repo-Bench; DeepSWE 1.1; QwenSWEBench; CoWorkBench; JobBench; Agents' Last Exam; IFBench; GPQA Diamond; HLE; LiveCodeBench v6; OSWorld-Verified; WebArena-Verified; AndroidWorld; RecreationBench; ClawEval-MM; SWE-MM; Vision2Web; MathVision; BabyVision; CharXiv (RQ); OmniDocBench 1.5; RealWorldQA; ERQA

## Qwen3.8-Flash-Next
- https://huggingface.co/Qwen/Qwen3.8-Flash-Next

Benchmarks as cited: DeepSWE 1.1; SWE-bench Pro; SWE-bench Multilingual; NL2Repo-Bench; CoWorkBench; JobBench; Agents' Last Exam; Toolathlon Verified (Pass@1); IFBench; GPQA Diamond; HLE; LiveCodeBench v6; ClawEval-MM; RecreationBench; AndroidWorld; OSWorld 2.0; Vision2Web; ERQA; LVBench; RealWorldQA; MathVision; CharXiv (RQ)

## Qwen-AgentWorld
- https://huggingface.co/Qwen/Qwen-AgentWorld-35B-A3B

Benchmarks as cited: MCP; Search; Term.; SWE; Android; Web; OS (aggregate AgentWorld suite columns; underlying benchmarks not itemized in table)

## DeepSeek-V4.1-Flash
- https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash

Benchmarks as cited: GPQA Diamond (Pass@1); HLE (Pass@1); Codeforces (Rating); MathArena Apex (Pass@1); Terminal-Bench 2.1 (Pass@1); Terminal-Bench 3.0 (Pass@1); Terminal-Bench 4.0 (Pass@1); DeepSWE v1.1 (Resolved); ProgramBench (Almost@1); NL2Repo-Bench (Score); CyberGym (Pass@1); SEC-Bench Pro (Pass@1); ExploitGym (Pass@1); HLE w/ tools (Pass@1); AutomationBench (Pass@1); Agent's Last Exam (Pass@1); Chartography w/ tools (Pass@1); BabyVision w/ tools (Pass@1); ZeroBench-main w/ tools (Pass@5); AGIEval; MMLU-Pro; C-Eval; MultiLoKo; SimpleQA-Verified; SuperGPQA; BBH; BBEH; DROP; HellaSwag; BigCodeBench; HumanEval; GSM8K; MATH; MGSM; LongBench-V2; MMMU-Pro; CVBench; DocVQA; RefCOCO-avg

## DeepSeek-V4-Pro-0813
- https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro-0813

Benchmarks as cited: HLE (wo / w tools); Terminal Bench 2.1; NL2Repo; Cybergym; DeepSWE; Toolathlon-Verified; Agents' Last Exam; AutomationBench (Public); DSBench-FullStack †; DSBench-Hard †

## DeepSeek-V4-Flash-0731
- https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731

Benchmarks as cited: Terminal Bench 2.1; NL2Repo; Cybergym; DeepSWE; Toolathlon-Verified; Agents' Last Exam; AutomationBench Public; DSBench-FullStack †; DSBench-Hard †

## DeepSeek-V4-Flash-Vision-Exp
- https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-Vision-Exp

Benchmarks as cited: Terminal Bench 2.1; NL2Repo; Cybergym; DeepSWE; Toolathlon-Verified; DSBench-Hard; AutomationBench (Public); ApexBench (Pass@1); Agents' Last Exam; Chartography; ZeroBench (Pass@5)

## Kimi K3
- https://huggingface.co/moonshotai/Kimi-K3

Benchmarks as cited: GPQA Diamond; CritPt; AA-LCR; HLE-Full; DeepSWE; ProgramBench; Terminal-Bench 2.1; FrontierSWE; SWE-Marathon; PostTrainBench; MLS-Bench-Lite; SciCode; Kimi Code Bench 2.0; BrowseComp; DeepSearchQA (F1); ResearchRubrics; GDPval-AA v2 (Elo); Toolathlon-Verified; MCPMark-Verified; MCP-Atlas; AutomationBench; JobBench; AA-Briefcase (Elo); Agents' Last Exam; APEX-Agents; OfficeQA Pro; SpreadsheetBench 2; OSWorld-Verified; OSWorld 2.0; SaaS-Bench; τ³-Banking; Harvey Lab-AA; CorpFin v2; Finance Agent v2; Legal Research Bench; WorldVQA ForceAnswer; OmniDocBench; PerceptionBench; Video-MME (w. sub); MMVU; BabyVision w/ python; MMMU-Pro; CharXiv (RQ); MathVision; ZeroBench (pass@5)

## Kimi K2.7-Code
- https://huggingface.co/moonshotai/Kimi-K2.7-Code

Benchmarks as cited: Kimi Code Bench v2; Program Bench; MLS Bench Lite; Kimi Claw 24/7 Bench; MCP Atlas; MCP Mark Verified

## Kimi K2.6
- https://huggingface.co/moonshotai/Kimi-K2.6

Benchmarks as cited: HLE-Full(w/ tools); BrowseComp; BrowseComp(Agent Swarm); DeepSearchQA(f1-score); DeepSearchQA(accuracy); WideSearch (item-f1); Toolathlon; MCPMark; Claw Eval (pass^3); Claw Eval (pass@3); APEX-Agents; OSWorld-Verified; Terminal-Bench 2.0(Terminus-2); SWE-Bench Pro; SWE-Bench Multilingual; SWE-Bench Verified; SciCode; OJBench (python); LiveCodeBench (v6); HLE-Full; AIME 2026; HMMT 2026 (Feb); IMO-AnswerBench; GPQA-Diamond; MMMU-Pro; MMMU-Pro (w/ python); CharXiv (RQ); CharXiv (RQ) (w/ python); MathVision; MathVision (w/ python); BabyVision; BabyVision (w/ python); V* (w/ python)

## MiniMax M3
- https://huggingface.co/MiniMaxAI/MiniMax-M3
- https://huggingface.co/MiniMaxAI/MiniMax-M3/resolve/main/figures/benchmark.jpeg

Benchmarks as cited: SWE-Bench Verified; SWE-Bench Pro; Terminal Bench 2.1; SWE Atlas-QnA; NL2Repo; SWE Atlas-Test Writing; SWE-fficiency; LiveSQLBench; CL-bench; VIBE-V2; SVG-Bench; PostTrainBench; KernelBench Hard; PaperBench; BrowseComp; DRACO; GDPval rubrics; BankerToolBench; OfficeQA Pro; SpreadSheetBench-v1; YC-Bench; LOCA-Bench (256k); MCP Atlas; Apex-Agents; Claw-Eval; OSWorld-Verified; OmniDocBench; MMMU-Pro; Video-MMMU; VideoMME (w/ sub); IMO 2025; USAMO 2026

## MiniMax M2.7
- https://huggingface.co/MiniMaxAI/MiniMax-M2.7

Benchmarks as cited: MLE Bench Lite; SWE-Pro; SWE Multilingual; Multi SWE Bench; VIBE-Pro; Terminal Bench 2; NL2Repo; GDPval-AA; Toolathon; MM Claw

## Claude Opus 5.5
- https://www.anthropic.com/claude-opus-5-5
- https://anthropic.com/claude-opus-5-5-system-card

Benchmarks as cited: Terminal-Bench 4.0; FrontierCode v1.1 (Main); CursorBench 4.0; GDPval-AA v2.1; AutomationBench; Humanity's Last Exam; Terminal-Bench-Science 0.1; OSWorld 2.0; Chartography; WANDR; SWE-bench Pro; SWE-bench Multilingual; SWE-bench Multimodal; DeepSWE v1.1; FrontierSWE v2; ArXivMath; ProgramBench; DRACO; Multi-agent ProgramBench; Multi-agent DRACO; Large agent teams; BenchCAD; OfficeQA; OfficeQA Pro; Legal Agent Benchmark; AA-Briefcase v1.1; Toolathlon Verified; HealthBench; HealthBench Professional; GMMLU; MILU; BioMysteryBench; LatchBio Bioinformatics (SpatialBench Verified, SingleCellBench); CoBench 2.1; AECI; ExploitBench; CyScenarioBench; Binary Exploitation Benchmark (formerly OSS-Fuzz); ExploitGym; BBQ; SHADE-Arena; LinuxArena; MASK

## Claude Sonnet 5
- https://www.anthropic.com/news/claude-sonnet-5
- https://www.anthropic.com/claude-sonnet-5-system-card

Benchmarks as cited: SWE-bench Pro; Terminal-Bench 2.1; Humanity's Last Exam; OSWorld-Verified; GDPval-AA v2; BrowseComp; SWE-bench Verified; SWE-bench Multilingual; SWE-bench Multimodal; FrontierCode; CursorBench; USAMO 2026; ArxivMath; ProgramBench; GDP.pdf; BenchCAD; ChartMuseum; CharXiv Reasoning; OfficeQA; Real-World Finance V2; Legal Agent Benchmark; Toolathlon; AutomationBench; AA-Briefcase; HealthBench; HealthBench Professional; GMMLU; MILU; INCLUDE; BioMysteryBench; LatchBio Bioinformatics; ProteinGym Hard; ExploitBench; OSS-Fuzz; CyberGym; Firefox 147; BBQ; SHADE-Arena; LinuxArena; MASK

## Claude Fable 5.1
- https://www.anthropic.com/claude-fable-and-mythos-5-1

Benchmarks as cited: Terminal-Bench-Science 0.1; Terminal-Bench 4.0; GDPval-AA v2; OSWorld 2.0; Humanity's Last Exam; AutomationBench; CursorBench 3.2.0

## GPT-6 Astra
- https://openai.com/index/gpt-6-astra/
- https://deploymentsafety.openai.com/gpt-6-astra

Benchmarks as cited: Agents' Last Exam; OSWorld 2.0 (v2026.08.08, offline set, partial score); ScreenSpot-Pro (no tools); Mind2Web; AutomationBench; BenchCAD; BrowseComp; OpenScore String Quartets (1 - OMR-NED); Internal Design Tasks; Internal Data Science Tasks; Artificial Analysis Intelligence Index v4.1.1; Terminal-Bench 4.0; DeepSWE v1.1; FrontierCode 1.1 Extended (score); FrontierCode 1.1 Main (score); Internal Database Migration Tasks; Artificial Analysis Coding Agent Index v1.4; Terminal-Bench Science 0.1; FrontierMath Tier 4 (v2); GPQA Diamond; Humanity's Last Exam (w/ tools); GeneBench Pro; MedChemBench (Internal); LifeSciBench; HealthBench Professional (length-adjusted); ExploitBench; ExploitGym; ExploitBench (June-Aug 2026); SRE-Bench; SEC-Bench Pro; Sandbox Bench; ExploitGym honeypot; Impossible ExploitGym; OpenAI MRCR v2 8-needle 256K-512K; OpenAI MRCR v2 8-needle 512K-1M; ARC-AGI-3; ARC-AGI-2; ARC-AGI-1; Internal Research Debugging Evaluation; KernelGen 1P; NanoGPT; PostTrainBench Lite; MLE-Bench Revised; ProtocolQA Open-Ended; TroubleshootingBench; Tacit knowledge and troubleshooting; Monorepo-Bench; Expert-SWE; HealthBench (Hard/Consensus)

## GPT-6 Sol / GPT-6 Luna
- https://openai.com/index/introducing-gpt-6-sol-and-luna/

Benchmarks as cited: AutomationBench 1.0.6; Agents' Last Exam V1; FrontierCode 1.1 Main; DeepSWE 1.1; OSWorld 2.0 (offline, v2026.08.08)

## GPT-5.6 Sol
- https://openai.com/index/gpt-5-6/

Benchmarks as cited: Agents' Last Exam; GDPval-AA v2; Management Consulting Tasks (Internal); Big Finance Bench; Artificial Analysis Intelligence Index v4.1; Artificial Analysis Coding Agent Index v1.1; SWE-Bench Pro; DeepSWE v1.1; Terminal-Bench 2.1; GeneBench Pro; LifeSciBench; MedChemBench (Internal); HealthBench Professional; OSWorld 2.0; BrowseComp; BenchCAD; BenchCAD (python tool); Capture-the-Flag Challenges; SEC-Bench Pro; ExploitBench; ExploitGym; Internal Research Debugging Evaluation; KernelGen 1P; NanoGPT; PostTrainBench Lite; RSI Index; MMMU Pro (no tools); MMMU Pro (with tools); gdp.pdf; GPQA Diamond; FrontierMath Tier 1-3 (v2); FrontierMath Tier 4 (v2); AutomationBench; Toolathlon; OpenAI MRCR v2 8-needle 256K-512K; OpenAI MRCR v2 8-needle 512K-1M; GraphWalks BFS 256k f1; GraphWalks BFS 1mil f1; ARC-AGI-3

## Gemini 3.8 Flash
- https://deepmind.google/models/model-cards/gemini-3-8-flash/

Benchmarks as cited: DeepSWE v1.1; GDPVal-AA v2; Vals Finance Agent v2; Harvey's Legal Agent Benchmark; Terminal-bench 2.1; Terminal-bench 4.0; GDP.PDF; CharXiv Reasoning; LVBench; HLE-Verified; OSWorld-2.0; BioMysteryBench; LABBench2

## Gemini 3.7 Flash
- https://deepmind.google/models/model-cards/gemini-3-7-flash/

Benchmarks as cited: Artificial Analysis Intelligence Index; FrontierCode 1.1 Main; DeepSWE v1.1; Code Arena; Terminal-bench 2.1; Terminal-bench 3.0; AutomationBench; GDPVal-AA v2; Harvey LAB-AA; GDP.pdf; CharXiv Reasoning; LVBench; GDM-MRCR v2 (8-needle); OSWorld-2.0; Agent's Last Exam; HLE-Verified; BioMysteryBench; LABBench2

## Grok 4.7
- https://x.ai/news/grok-4-7

Benchmarks as cited: CursorBench 4.0; DeepSWE v1.1; EEBench; AA Briefcase v1.1; Terminal-Bench 4.0; Harvey Legal Agent Benchmark; HealthBench Professional; GDPval; LatchBio biosafety benchmark; HackerBench v0.3

## Mistral Medium 3.5
- https://huggingface.co/mistralai/Mistral-Medium-3.5-128B

Benchmarks as cited: SWE-Bench verified; τ³ Telecom; τ³ Airline; τ³ Retail; τ³ Banking; BrowseComp; AIME25 avg@16; Allenai Ifbench; Collie; Beyond AIME avg@16

## Mistral Small 4
- https://huggingface.co/mistralai/Mistral-Small-4-119B-2603

Benchmarks as cited (from the image alt text and card body; the chart images themselves were not read): LCR (image); LiveCodeBench; AIME25

## Nemotron 3 Ultra
- https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16

Benchmarks as cited: Terminal Bench 2.1; GDPVal; SWE-Bench Verified; SWE-Bench Multilingual; ProfBench (Search); PinchBench; TauBench V3 (Airline/Retail/Telecom/Banking); BrowseComp; Vals.ai Financial Agent 1.1; IOI 2025; LiveCodeBench (v6); IMOAnswerBench; Apex-Shortlist; GPQA; SciCode (subtask); HLE; CritPt; MMLU-Pro; OmniScience; IFBench (prompt loose); Multi-Challenge; AA-LCR; RULER (1M); Longbench v2; MMLU-ProX; WMT24++

## Nemotron 3.5 Lightning
- https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16

Benchmarks as cited: MMLU Pro; AA-Omniscience; GPQA Diamond (no tools); HLE (text-only, no tools); SciCode; SWE-bench Verified; SWE-bench Multilingual; Terminal-Bench 2.1; PinchBench; BrowseComp; τ³-bench (Banking); GDPval-AA-V2; IFBench (loose); AA-LCR

## Notes on scope

- Qwen-AgentWorld-35B-A3B reports only aggregate AgentWorld columns (MCP, Search, Term., SWE, Android, Web, OS). The underlying benchmarks are not itemized, so the catalog has no entries for them.
- DeepSeek-V4.1-Flash base-model rows (AGIEval, MMLU-Pro, C-Eval, MultiLoKo, SimpleQA-Verified, SuperGPQA, BBH, BBEH, DROP, HellaSwag, BigCodeBench, HumanEval, GSM8K, MATH, MGSM, MMMU-Pro, CVBench, DocVQA, RefCOCO) are static base-model evals. They are left out of the catalog except where an instruct/agentic card also cites them (LongBench v2, MMMU-Pro).
- Unnamed internal safety evals (for example the OpenAI 'Internal computer use safety benchmark' and 'Internal hallucination benchmark', and Gemini's automated safety evals) are not cataloged.
- Anthropic system cards also report alignment and safety evals such as SHADE-Arena, LinuxArena, MASK and BBQ. These are cataloged because they are named, reusable benchmarks.
- GLM-5.3-Flash benchmark chart: bench_53.png (6 benchmarks: Terminal Bench 2.1, DeepSWE v1.1, Agents' Last Exam, AutomationBench v1.0.6, HLE w/ Tools, GDPVal-AA v2). Footnotes also cover NL2Repo, Toolathlon Verified and BabyVision.
- MiniMax M3 and Mistral benchmark tables were only available as images, which were read visually.
