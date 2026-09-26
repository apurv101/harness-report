# Taskset expansion — September 26, 2026

The first rollout added **25 validated tasks**, taking coverage from **14 to 24 tasksets** and reaching **75 enabled tasks** at that point. The subsequent full-corpus validation is tracked in [VALIDATION-PROGRESS.md](VALIDATION-PROGRESS.md); its passing tasks are enabled automatically, so the live total can now be higher. Candidate tasks still require a successful latest reference result to remain enabled.

| Taskset | Newly enabled tasks |
| --- | ---: |
| DS-1000 | 3 |
| DA-Code | 3 |
| SpreadsheetBench | 3 |
| ScienceAgentBench | 1 |
| GAIA | 3 |
| Terminal-Bench 2.1 | 3 |
| DevOps-Gym | 1 |
| τ³-bench | 3 |
| KUMO | 3 |
| CooperBench | 2 |

Exact task names, reference scores, negative controls, timestamps and log locations are in [catalog/expansion.json](catalog/expansion.json). All 25 selected reference solutions scored 1 under their original graders; all 25 empty submissions scored 0. These are admission checks for these particular tasks, not a universal interpretation of rewards or evidence of any real harness's performance.

CooperBench `cb-chi-t26-f1-3` remains excluded: its reference solution scored 0 because one feature test failed. Its tests were preserved.

## Execution support

CooperBench now runs the selected harness independently in both worker containers. Each receives its own original feature prompt and repository copy, with Redis messaging available through `send_message` and `check_messages`. The original grader merges the two submitted patches and runs both feature test suites. The coordinator records each worker's exit status. Reference trials leave the workers idle, avoiding unrelated model calls. A deterministic harness fixture exercised both workers, exchanged messages, submitted patches, and scored 1 through the real merge grader.

Task-declared HTTP MCP servers are available to shell-capable harnesses through `hr-mcp`. The task prompt explains how to discover and call the tools. A real τ³ runtime check verified tool discovery and a status call without invoking the simulated user's model. Full conversational performance still depends on the selected harness and configured model service.

The τ³ environment uses the corpus's recorded tau2 source commit and includes its missing websocket import dependency. KUMO and CooperBench descriptive result files were renamed from `reward.json` to `result.json` so Harbor reads the existing scalar `reward.txt`; the scoring rules were preserved.

These corpus changes are checksum guarded and reproducible:

```sh
python3 lib/apply_expansion_patches.py "$HARBOR_TASKS"
python3 lib/apply_expansion_patches.py "$HARBOR_TASKS" --check
```

The full patch ledger is [catalog/expansion-patches.json](catalog/expansion-patches.json).

## Corpus and validation

Terminal-Bench 2.1 was missing from the downloaded corpus. Its 89-task release was downloaded by content digest, recorded in [catalog/expansion-source.json](catalog/expansion-source.json), and registered in `TASK-INDEX.json`. The corpus now contains 101 downloaded tasksets and 93,639 indexed tasks. Only the validated selections are enabled.

Validation completed on `linux/amd64` containers:

- 25 reference checks and 25 successful empty-submission controls.
- Real CooperBench worker and τ³ MCP integration checks.
- 68 repository regression tests.
- No remaining containers, networks or volumes from the Harbor validation trials.

To repeat the adapter checks after building the corresponding base images:

```sh
python3 tests/expansion_docker_smoke.py cooperbench
python3 tests/expansion_docker_smoke.py tau3-bench
python3 tests/validate_empty_submissions.py TASKSET/TASK
python3 -m unittest discover -s tests -p 'test_*.py'
```

Reference checks use `./run.sh oracle TASKSET TASK1,TASK2`. Full local evidence, including failed attempts and subsequent corrections, is retained in [catalog/oracle.jsonl](catalog/oracle.jsonl) and [catalog/expansion-validation.jsonl](catalog/expansion-validation.jsonl).

## Publication

The ten tasksets were published to the configured **local** DynamoDB catalog. AWS worker deployment, task upload and hosted catalog publication have not been performed by this expansion. Deploy the updated runner and patched task files before exposing these selections on the hosted service; see [CLOUD.md](CLOUD.md).

## Full-corpus validation

The user authorized validation across all **9,295 tasks** in these ten tasksets, with publication to the **local catalog first**. The batch uses six workers, reserves memory for Docker and the local catalog, and keeps a 10 GiB free-disk reserve. Docker was increased from its 8 GiB default to 24 GiB with explicit user approval; the prior setting is recorded in `work/validation-batch/docker-memory-change.json`.

`lib/validate_corpus.py` runs the original solution and grader, then runs the empty-submission control in a fresh environment. A numeric reward alone cannot hide a failed reference process or a backend error. Each completed pair is saved before local catalog publication. Previously validated tasks are retained. Identical DS-1000 runtime images are reused; every task still has fresh containers, its own solution, and its own grader.

Known template fixes are extended only when the source checksum matches a previously reviewed patch. Their per-file checksums are recorded in `catalog/validation-adapter-patches.jsonl`. Grading rules are preserved.

GPU-dependent tasks, tasks requiring a visual judge service that this batch has not configured, missing reference solutions, and unavailable environments remain disabled with explicit reasons. Failed tasks also remain disabled. The batch does not deploy to AWS.

```sh
python3 lib/validate_corpus.py status
# Resume after interruption, skipping completed checks:
python3 lib/validate_corpus.py run --workers 6
# Retry failed/blocked checks after their prerequisites have been addressed:
python3 lib/validate_corpus.py run --workers 6 --retry
```

Read [VALIDATION-PROGRESS.md](VALIDATION-PROGRESS.md) for current totals and `work/validation-batch/full-run.log` for the active batch console. Detailed per-task records live in `catalog/validation-results.jsonl`. The active process is recorded in `work/validation-batch/process.json`; idle sleep is inhibited only while that process runs.
