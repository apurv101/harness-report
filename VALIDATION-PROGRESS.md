# Full taskset validation

Updated: 2026-09-26T03:36:44Z. Batch state: **running**.

Validation and publication are local only. Passing means the reference solution scored 1 and a fresh empty submission scored 0; failed and blocked tasks remain disabled.

| Taskset | Total | Passed | Failed | Blocked | Pending |
| --- | ---: | ---: | ---: | ---: | ---: |
| ds1000 | 1000 | 6 | 0 | 0 | 994 |
| dacode | 479 | 6 | 0 | 0 | 473 |
| spreadsheetbench-verified | 400 | 6 | 0 | 0 | 394 |
| scienceagentbench | 102 | 1 | 3 | 2 | 96 |
| gaia | 165 | 5 | 0 | 0 | 160 |
| terminal-bench-2-1 | 89 | 6 | 2 | 0 | 81 |
| devopsgym | 733 | 1 | 5 | 0 | 727 |
| tau3-bench | 375 | 8 | 0 | 0 | 367 |
| kumo | 5300 | 7 | 0 | 0 | 5293 |
| cooperbench | 652 | 5 | 0 | 0 | 647 |

**51 validated tasks** across these tasksets; 9232 pending. Passing tasks are published automatically; any publication failures are recorded separately.

Detailed evidence: [validation-results.jsonl](catalog/validation-results.jsonl).
Run `python3 lib/validate_corpus.py status` for live stages and `python3 lib/validate_corpus.py run` to resume after interruption.
Blocked tasks can be retried with `--retry` once their prerequisites are available.

Currently working on:
- scienceagentbench/sab_11: building
- gaia/05407167-39ec-4d3a-a234-73a9120c325d: building
- terminal-bench-2-1/build-pov-ray: building
