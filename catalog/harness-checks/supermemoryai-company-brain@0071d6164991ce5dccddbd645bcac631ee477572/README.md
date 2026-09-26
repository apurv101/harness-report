# Company Brain compatibility check

[Company Brain](https://github.com/supermemoryai/company-brain/tree/0071d6164991ce5dccddbd645bcac631ee477572) is registered in the local harness catalog as **Needs integration**. It is an Apache-2.0 Slack agent application on Cloudflare Workers, with a Durable Object agent, memory, connected tools, and optional Cloudflare/Daytona code sandboxes.

The upstream source was not modified. No Slack account, Supermemory account, cloud deployment, or model service was connected. These are installation, component-test and startup checks; there are **zero benchmark runs and no reward**.

## Observed results

| Check | Result |
| --- | --- |
| Frozen dependency installation | Succeeded |
| `bun test` | 39 passed across 11 files |
| `bun run test` with Node 22 | 31 passed; two suites failed to resolve TypeScript path aliases |
| `bun run build` | Worker and web build succeeded; dry run only |
| Local worker with Node 22 | Database migration applied; `/health` returned HTTP 200 and `{"ok":true}` |

The two failing package-test suites are `src/brain/codemode/quickjs-executor.test.ts` and `src/brain/tools/mcp/catalog.test.ts`; see `package-test.log` for their exact diagnostics. The Bun configuration includes a Workers shim and uses the project's TypeScript path mappings. Bun-only Wrangler startup stalled; supplying Node 22 resolved the local startup check.

The checks ran on Linux arm64, using Bun 1.4.2 and Node 22.23.3. Exact image digests, command names, log checksums and results are in `checks.json`; `tools.Dockerfile` reproduces the tool runtime. They do not establish compatibility with the amd64 benchmark runner.

## Remaining integration

The release has no command-line task entrypoint. Its internal `debugTurn` method is a possible adapter boundary, but the public worker routes do not expose it as a benchmark API. An adapter must deliver the instruction and capture completion while retaining the original agent loop.

Its file tools operate in Cloudflare or Daytona sandboxes. Those tools must work against the task's actual files and return state that the original grader can inspect. A separately cloned repository in a remote sandbox would not validate this requirement.

Company-memory evaluations also need isolated memory and task-scoped tool connections. The installation checks used none of the user's company data.

The installed `@ai-sdk/anthropic` 3.0.98 does support `ANTHROPIC_BASE_URL`, so a configurable model endpoint is not a confirmed blocker. A complete model turn through our recorder still needs validation.

## Repeating the checks

Use the pinned upstream revision, build `tools.Dockerfile`, and run the commands in `checks.json` in a disposable container. Keep Node on PATH for Wrangler; use the repository's `bun test` for the shipped Bun test configuration. `bun run test` is a separate check and currently exits 1. Start the worker with `bun run dev --local --ip 127.0.0.1 --port 8787`, then request `/health`; stop it after the check. No deployment is needed.

Restore this reviewed entry into the local catalog with:

```sh
HR_DDB=local HR_DDB_ENDPOINT=http://127.0.0.1:8001 \
  python3 lib/store.py sync --harnesses --grep '^supermemoryai-company-brain$'
```

Its profile is stored under `profiles/` for this exact commit. The catalog supports reviewed entries before a recipe or benchmark run exists, and ties compatibility findings to the reviewed revision.
