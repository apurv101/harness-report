# Full taskset validation

Updated: 2026-09-26T04:43:59Z. Batch state: **running**.

Validation and publication are local only. Passing means the reference solution scored 1 and a fresh empty submission scored 0; failed and blocked tasks remain disabled.

| Taskset | Total | Passed | Failed | Blocked | Pending |
| --- | ---: | ---: | ---: | ---: | ---: |
| ds1000 | 1000 | 13 | 0 | 0 | 987 |
| dacode | 479 | 13 | 0 | 0 | 466 |
| spreadsheetbench-verified | 400 | 13 | 0 | 0 | 387 |
| scienceagentbench | 102 | 1 | 7 | 5 | 89 |
| gaia | 165 | 12 | 0 | 0 | 153 |
| terminal-bench-2-1 | 89 | 12 | 3 | 0 | 74 |
| devopsgym | 733 | 1 | 11 | 0 | 721 |
| tau3-bench | 375 | 15 | 0 | 0 | 360 |
| kumo | 5300 | 14 | 0 | 0 | 5286 |
| cooperbench | 652 | 12 | 0 | 0 | 640 |

**106 validated tasks** across these tasksets; 9163 pending. Passing tasks are published automatically; any publication failures are recorded separately.

Detailed evidence: [validation-results.jsonl](catalog/validation-results.jsonl).
Run `python3 lib/validate_corpus.py status` for live stages and `python3 lib/validate_corpus.py run` to resume after interruption.
Blocked tasks can be retried with `--retry` once their prerequisites are available.

Currently working on:
- devopsgym/build_bugfix_elastic-logstash-49712772520: reference
- scienceagentbench/sab_18: building
- gaia/0b260a57-3f3a-4405-9f29-6d7a1012dbfb: building
