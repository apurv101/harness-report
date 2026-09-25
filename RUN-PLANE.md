# The run plane

How a task submitted on harnessreport.com becomes a container on AWS. Design, 2026-09-24.

Everything below is measured against the 43 local runs in `runs/`, the 160 local images, and the
`~/Desktop/harbor-tasks` corpus — not estimated.

## What the workload actually is

| fact | measured | what it forces |
|---|---|---|
| agent run length | p50 **53 s**, p90 286 s, max 1192 s | boot latency is the same order as the job — it is not amortised away |
| model calls per run | p50 8 | the container is **idle waiting on the model** almost the whole run → pack many per host |
| overlay image size | 1.3–5.2 GB, median ~2 GB | a cold pull (25–60 s) nearly doubles a p50 run |
| output per run | 13.4 MB | S3 per run folder is free in practice |
| containers per run | 2 (sandbox + proxy), 2 networks | one task = one container is already true today |
| architecture | linux/amd64 | the 37 GB / 85-taskset Harbor corpus is amd64 — **no Graviton runners** |
| daemon | `docker build`, `exec`, `cp`, `network create` | anything without a Docker daemon cannot run `run.sh` unchanged |
| task images in a taskset | all 225 `aider_polyglot` tasks are `FROM buildpack-deps:jammy` with identical apt layers | the layer cache on one host makes task image 2..N nearly free |

## Where the seconds go

| step | cold (new harness, new host) | warm (recipe + overlay cached) | hot (same host, 2nd task) |
|---|---|---|---|
| acquire a machine | 40–90 s EC2 boot | 0 s (warm pool) | 0 s |
| `git clone` | 2–10 s | 0 s (cached) | 0 s |
| `claude -p` analyzer | **~120 s, $0.6–$11** | 0 s (recipe cached by repo@commit) | 0 s |
| task image | 60–180 s build | 20–45 s pull | **0 s** |
| overlay build | 60–180 s | 25–60 s pull from ECR | **30–90 s — a full harness reinstall, every task** (see below) |
| container + proxy start | 4 s | 4 s | **4 s** |
| **to first model call** | **4–6 min** | **~50 s** | **~35–95 s today, ~5 s on tier 0** |

The whole design is the three caches that move a user from the left column to the right one:
the **recipe** (S3, keyed `repo@commit`), the **overlay image** (ECR, keyed `harness@commit/taskset:task`),
and the **layer cache on the host** (worth 30–60 s per run and only exists if runs share a host).

But measure *which* layers the host cache actually holds, because it is not the obvious ones — see
**Which way round the image is built** below.

## The question: one VM per task, or one VM per user?

**Answer: one VM per evaluation session (user × harness), many task containers on it.**
The container is the boundary per task; the VM is the boundary per *tenant*.

1. **Image locality is worth 30–60 s on a 53 s job.** Measured on the local images: two *different* harnesses
   built on the same task base share **13 of their layers**; the same harness built on its own base vs on a task
   base shares **1 of 18**. So the host cache that pays is the **task base**, shared across every harness and
   every task in a taskset. Spreading tasks across VMs throws that away every time.
2. **The runs are I/O-bound on the model**, not CPU-bound (p50 8 calls in 53 s). A 16-vCPU host packs 8
   concurrent 2-vCPU task containers with headroom. One VM per task idles ~90% of the CPU it pays for.
3. **The analyzer is per harness, not per task** — it is naturally session-scoped, and its output
   ($0.6–$11 each) is the thing you most want to compute once.
4. **The tenant boundary is the user, not the task.** Tasks inside one session are the same trust level
   (their repo, their agent). Two users must never share a kernel.

Use a VM per task only where the session model breaks: `task.toml` asking for most of a host, multi-container
(docker-compose) tasks, and batch sweeps where spot instances should die independently.

## Which way round the image is built

**The task is the base; the harness is the overlay.** Not the other way round. `task_image()` builds
`<task>/environment/Dockerfile` into an image, that image is passed as `ARG BASE`, and the recipe's Dockerfile
must begin `ARG BASE=…` / `FROM ${BASE}` — `run.sh` rejects any recipe that does not. The analyzer is told, in
so many words: *never rely on or change the base image's python/node/packages; install the harness runtime
self-contained under `/opt/harness`* (uv with `UV_PYTHON_INSTALL_DIR` under `/opt/harness`, or an official node
tarball unpacked there).

### Why the other direction cannot work

| measured over the 49,195-task corpus | consequence |
|---|---|
| 49,170 tasks ship their own `environment/Dockerfile`, each pinning its own base | there is no single "harness image" a task environment could be installed onto |
| top 8 bases = **81%** of all tasks; the tail is vendor images (`swelancer/swelancer_x86_monolith`, `jyangballin/swesmith.x86_64.*`, `futurehouse/bixbench`, `jasonchou97/sandbox`) | the tail is published, opaque, per-instance — nothing to replay onto anything |
| 25 tasks have no Dockerfile at all, only a `docker_image` | literally nothing to install |
| `tests/test.sh` runs in the task's own image | mutating the environment makes the reward incomparable to the published number |

### But harness-over-task is not always possible either

It is the direction that *usually* works, not the one that always works. What actually breaks, and where it stands:

| failure mode | status |
|---|---|
| harness bin dir hidden by the task image's own `PATH` | **solved** — `HR_PATH` + `PRELUDE` carry and restore the image's PATH (`lib/common.sh`) |
| harness needs a different python/node than the task's | **solved** — vendored under `/opt/harness`, system interpreter untouched |
| base has no `apt-get` (alpine/musl/distroless) | **not a real risk here** — measured **0** of 49,170 tasks use one |
| base's glibc older than what the harness's wheels/binaries need | **open** — the floor must be measured against the bake list before relying on it |
| harness wants to *be* the container (own entrypoint, own docker daemon) | **open** — needs tier 2 below; 224 tasks already base on `cruizba/ubuntu-dind` |
| multi-container (docker-compose) tasks | **skipped today**, by design |
| nothing works | **already the right answer** — a harness that cannot run on a given environment is a finding to record, not a bug to patch around |

The three-attempt analyzer loop *is* the admission that this is not universal, and `check_command` run with
`--network none` inside the built image is the gate that decides.

### The cost this direction imposes, and the ladder out of it

Because the overlay's parent changes with every task image, **Docker's build cache misses every step**: a
20-task sweep reinstalls the harness 20 times. That is the largest avoidable cost in the pipeline.

| tier | mechanism | per-task build | when it applies |
|---|---|---|---|
| **0** | build `/opt/harness` **once** on the oldest-glibc base in the bake list, ship it as a bundle, `-v bundle:/opt/harness:ro` into the unmodified task container | **none** | whenever `check_command` passes in the task image with only the bundle mounted. The vendoring rule already makes the tree relocatable *by construction* — this tier is the payoff for it |
| **1** | today's overlay build `FROM` the task image, plus BuildKit cache mounts for the uv/npm/apt downloads | 30–90 s | when the harness needs apt packages or files outside `/opt/harness` |
| **2** | harness in its own sidecar container, task container untouched, driven over `docker exec` | none | harnesses that need their own OS or their own docker daemon |
| **3** | refuse and record | — | the finding, per the never-modify rule |

Tier 0 is the single change that would make a second task on a warm host cost ~5 s instead of 30–90 s, and it
also makes the task image bit-identical to the published one, which is worth more than the seconds. It needs a
probe, not faith: build the bundle, run `check_command` in each target task image, and record which tier each
harness lands in on its report card.

### The bake list

A task's *base* is the first `FROM` in its own `environment/Dockerfile` — the bottom of the stack, before the
harness overlay goes on top. Across the corpus there are **5,305 distinct bases for 49,170 tasks**, and the
distribution is head-heavy then flat:

| rank | base | tasks | cum. |
|---|---|---|---|
| 1 | `python:3.11-slim` | 20,663 | 42% |
| 2 | `ghcr.io/laude-institute/t-bench/python-3-13:20250620` | 4,907 | 52% |
| 3 | `python:3.10-slim` | 4,899 | 62% |
| 4 | `python:3.12-slim` | 2,292 | 67% |
| 5 | `python:3.11-slim-bookworm` | 1,977 | 71% |
| 6 | `ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624` | 1,835 | 74% |
| 7 | `python:3.13-slim-bookworm` | 1,654 | 78% |
| 8 | `debian:bookworm-slim` | 1,601 | **81%** |

Baking 8 images buys 81%; baking 50 buys 88%. Stop at 8 — the next 42 images cost disk for 7 points.

### The irreducibly cold 19%

**4,681 of the 5,305 distinct bases (88%) are used by exactly one task**: per-instance vendor builds —
`xingyaoww/*` (2,208), `swebench/*` (800), `jefzda/*` (731), `michaelyang335/*` (433), `swelancer/*` (198).
One image per task, by construction, so there is nothing to pre-cache and nothing to share.

This splits the fleet policy in two, and the split is real:

| corpus | shape | policy |
|---|---|---|
| the 81% head (`aider_polyglot`, terminal-bench, most of the corpus) | shared base, cached on the host, overlay is the only build | **session VM, many task containers** — the layer cache is the whole win |
| the SWE-bench-style tail (`swebench-verified`, `swegym`, `swebenchpro`, `swtbench`, `swesmith`, `swe-lancer`) | unique 1–2 GB image per task, zero reuse | **one container per task on spot**, pulls in parallel — there is no cache to preserve, so co-location buys nothing |

## Options considered

| option | boot to first call | can build images | verdict |
|---|---|---|---|
| **EC2 runner fleet + warm pool** | ~4 s hot / ~50 s warm | yes | **chosen.** `run.sh` runs unmodified; the layer cache is the product's main asset |
| ECS/Fargate, one task per run | 10–20 s start + 25–60 s pull, every run | **no** | pull cost on every run, and the build stage needs CodeBuild anyway. Good later for the *proxy*, not the sandbox |
| AWS Batch / Step Functions Map on spot | tens of s–min scheduling | yes (EC2 mode) | **chosen for batch sweeps only** — wrong for a user watching a page |
| E2B / Daytona / Modal (rented microVMs) | ~1 s from template | no (templates built from images, out of band) | **no for the measurement plane.** E2B's UTF-8 output decoding corrupts framed stdio — we would be publishing the sandbox's quirks as the harness's failures. Keep as overflow capacity, never as the reference runtime |
| EKS + Karpenter | same as EC2 | yes | same answer as EC2 with a control plane we do not need yet |
| Lambda | — | no | 15 min cap, no daemon. Right for the *control* plane |
| Bedrock AgentCore | — | no | ARM64-only, 2 vCPU / 1 GB session disk, no daemon. Already ruled out 2026-09-23 |

## Architecture

```
site (Cloudflare Pages)  ->  serve.py / API (Lambda + DDB)  ->  SQS  ->  runner EC2 (warm pool)
                                     |                                        |
                                  run state                             one container per task
                                  (DynamoDB)                            + one proxy per run
                                     |                                        |
                              S3: runs/<run-id>/  <---------------------------+
                              S3: recipes/<repo>@<commit>.json
                              ECR: <harness>@<commit>/<taskset>:<task>
```

**Control plane** — Lambda + DynamoDB + Step Functions (no servers, no run ever executes here).
`POST /api/runs` writes a run row and enqueues a *session lease*: `(user, repo@commit, taskset, tasks, k)`.

**Session allocator** — picks an instance tagged `hr:state=free` from the warm pool, tags it
`hr:state=leased, hr:user=<id>, hr:harness=<repo@commit>`; scales the ASG if none is free. A lease is sticky:
every run of that session goes to the same box, which is the entire point.

**Runner AMI** — AL2023 + Docker + `hr-agentd` (a ~200-line poller) + pre-pulled `hr-proxy`,
`buildpack-deps:jammy`, and the base images of the tasksets we offer. Docker's data-root is on
**instance-store NVMe**, not EBS: image unpack is disk-bound, and an EBS AMI lazily loads its blocks from S3
on first read, which is exactly the wrong shape. The instance pulls its hot image set at boot and only then
tags itself `free` — in a warm pool, warm-up costs nothing as long as the pool is deeper than arrivals during
warm-up (at 10 runs/hour, **2 hot instances**).

**hr-agentd** — leases from SQS, runs the existing `run.sh` stages, streams stage events to DynamoDB (what
`/#runs/<id>` already renders), syncs the run folder to S3 on completion, extends or drops the lease.

**Teardown** — idle 10 min → `shutdown -h now` with `InstanceInitiatedShutdownBehavior=terminate`. Disposable
by default; the disk is a cache, never state.

**Fan-out for sweeps** — the session box builds the overlay once and pushes it to ECR; a Step Functions Map
then spreads `tasks × k` over N **spot** instances that pull that overlay. Latency stops mattering the moment
nobody is watching, so batch buys ~70% off.

**Instance shape** — x86 with NVMe: `c6id.2xlarge` (8 vCPU / 16 GB / 474 GB) for interactive sessions,
`c6id.4xlarge` for sweep shards. 474 GB holds ~100–200 overlays; `hr-agentd` GCs by LRU below 80%.

## The runner OS

The box is a **cache with a CPU attached**. Nothing on it is state: no user data survives the session, the disk
holds only images and a run folder in flight, and the instance terminates rather than being repaired. Every
choice below follows from that.

**Distro: Ubuntu 24.04 LTS + `docker-ce` pinned from Docker's own repo.** The design leans on current BuildKit
(registry cache export, cache mounts) and on the containerd image store, and pinning `docker-ce` to the same
major as the laptop that generated the recipes removes a whole class of "worked locally" drift — the local
daemon is 29.4.3. AL2023 is the lower-maintenance alternative (SSM agent and cloud-init preinstalled, AWS
kernel) at the cost of a docker package that lags; take it if fleet upkeep matters more than build features.
The host kernel is shared with every container, so this is a real choice, not a preference.

**Disk.** Root EBS stays small (30 GB, OS only). `/var/lib/docker` goes on **instance-store NVMe**, formatted
at every boot:

```
nvme → mkfs.ext4 -m0 → mount -o noatime,nodiratime /var/lib/docker
```

`-m0` because no reserved blocks are wanted on a cache, `noatime` because nothing reads atime and image unpack
writes millions of inodes. Ephemeral storage is wiped on stop, which is correct here and is also why the
instance must be *terminated*, never stopped. No swap: when a build or an agent blows its budget the cgroup
should OOM-kill it, not thrash the host — `codex-rs` already OOMs at 8 GB and that is a finding, not a
condition to paper over.

**Boot sequence** (cloud-init user-data), in order, before the instance advertises itself:

1. format and mount the NVMe, start docker
2. `docker pull` the 8 bake-list bases **in parallel**, plus `hr-proxy`
3. warm BuildKit (`docker buildx create --use`)
4. tag self `hr:state=free`

Steps 2–3 are why a warm pool exists: warm-up is invisible as long as the pool is deeper than arrivals during
warm-up.

**Sysctls that this workload actually hits** — all of these have bitten agent sandboxes:

| setting | why |
|---|---|
| `fs.inotify.max_user_instances` / `max_user_watches` | agents and the dev servers they start watch files; the default instance count is low once a host runs 8 containers |
| `net.netfilter.nf_conntrack_max` | every container's traffic is NAT'd to the proxy; a chatty agent plus 8 containers exhausts the default table and connections start failing intermittently — which reads as a flaky harness |
| `kernel.pid_max` + per-container `--pids-limit` | a runaway agent fork-bombs the host otherwise |
| `nofile` ulimit | node and python toolchains open a lot of descriptors |
| `vm.max_map_count` | JVM and search-index tooling in some task images |

**Clock.** Amazon Time Sync via chrony. SigV4 and TLS both fail on skew, and a run that dies from clock drift
looks exactly like a harness bug on the report card.

**Access.** No SSH, no keys, no open port 22. SSM Session Manager only — which is also the path to the
live-run view worth stealing from AgentCore's `InvokeAgentRuntimeCommandShell`.

## What a harness may and may not do

The analyzer writes the install, so the contract is a *prompt* contract plus a *build* gate, not documentation.
Measured across the 41 recipes generated so far:

| rule | why | enforced by | measured |
|---|---|---|---|
| Dockerfile is an overlay: `ARG BASE=…` then `FROM ${BASE}` | the task owns the container | `recipe_ok` rejects the recipe outright (`lib/recipe.sh`, `lib/recipe.py ok`) | 41/41 |
| runtime vendored self-contained under `/opt/harness` | the task's own python/node must stay untouched or its tests break | analyzer prompt; `check_command` in the task image | 41/41 |
| `apt-get` only what is genuinely missing | every apt package is a mutation of the task environment | analyzer prompt | **41/41 use apt-get** — nothing is pure `/opt/harness` |
| PATH via `ENV` *and* `/etc/profile.d` | Debian's `/etc/profile` resets PATH for `bash -lc`, which would hide `/opt/harness/bin` | `HR_PATH` + `PRELUDE` (`lib/common.sh`) | in the generated overlays |
| the harness source is never modified | the standing rule: a harness that cannot run is a finding | analyzer prompt | — |
| no secrets baked, harness never run at build | the image is cached and shared across users | analyzer prompt | — |
| no network at run time except the proxy | the whole measurement depends on it | `--internal` network, no route out | — |
| `check_command` passes with `--network none` | proves the install without spending a model call | `check_image` (`lib/recipe.sh`) | the gate for all three tiers |

The apt row is the important one. The packages are few and stable:

```
curl 30   ca-certificates 30   git 29   xz-utils 14   bash 11
procps 7  unzip 5              ripgrep 4  tmux 2
```

That is a *hoistable* set — which is what makes tier 0 plausible. Only **5 of 41** recipes write anywhere
outside `/opt/harness` at all, and the bundles are small: measured `/opt/harness` sizes are **51 MB
(neoagent), 490 MB (codex), 594 MB (mini-swe-agent), 635 MB (openhands)** — mountable, not image-sized.

### Rules the hosted plane has to add

None of these are in the analyzer prompt yet, and each is a real failure waiting on a runner:

1. **No docker socket, no `--privileged`, no docker-in-docker.** Mounting `/var/run/docker.sock` is root on the
   host. A harness that needs its own daemon goes to tier 2. Note the corpus already contains **224 tasks based
   on `cruizba/ubuntu-dind`** that want a daemon *themselves* — that is the task's need, not the harness's, and
   it needs a separate decision.
2. **Do not assume a user.** **0 of 6,000 sampled task Dockerfiles set `USER`**, so containers run as root
   today — but 1 of 41 recipes sets `USER`, which will break the moment a task image sets its own.
3. **Write only to** `/opt/harness` (read-only at run time under tier 0), the task workdir, `/out`, `/tmp`.
   Never `/tests` — the proxy already flags tool calls that touch them.
4. **Relocatable or declare it.** Tier 0 requires no absolute paths compiled in outside `/opt/harness`. The
   vendoring rule gets this for free in most cases; the probe is what proves it per harness.
5. **Build-time network is allowed but recorded.** Builds pull from PyPI/npm/GitHub. That is supply chain in
   the measurement path, and at minimum it belongs in the run record.
6. **Budgets.** Overlay delta and install wall-clock both need a ceiling, or one pathological repo eats a
   runner's disk (locally: 246 GB of images, 74.7 GB of build cache).

## Docker on the runner

```jsonc
{
  "data-root": "/mnt/nvme/docker",          // instance store, not EBS
  "storage-driver": "overlay2",
  "default-address-pools": [                // see below — the trap
    {"base": "10.200.0.0/12", "size": 24}
  ],
  "max-concurrent-downloads": 10,           // the cold 19% pulls unique 1–2 GB images
  "log-driver": "json-file",
  "log-opts": {"max-size": "64m", "max-file": "3"},
  "live-restore": false,                    // the instance is disposable
  "features": {"containerd-snapshotter": true}
}
```

**The address-pool trap.** The per-run network fix in the prerequisites means **two networks per run**. Docker's
built-in pools yield only ~30 user-defined networks before `docker network create` starts failing, so a host
running 8 concurrent runs is within a factor of two of the ceiling — and the failure mode is a mid-sweep error
that looks like anything but an address pool. Configure `default-address-pools` explicitly with `/24`s, and
have `hr-agentd` reap orphaned `hr-net-*` / `hr-int-*` networks on run teardown. (Verify the exact default
count on the runner; the fix is cheap either way.)

**Builds.** `docker buildx` with:

- `RUN --mount=type=cache` for the uv/npm/apt downloads, so they survive the overlay being rebuilt against a
  new task base (tier 1's only real mitigation)
- `--cache-to`/`--cache-from type=registry` against ECR, so a build on one runner warms every other runner
- a memory limit on the *build*, not just the run — an unbounded build is how you OOM the host rather than the
  container

**Lazy pulls for the cold tail.** The containerd image store plus a stargz/SOCI snapshotter lets a 1–2 GB
SWE-bench image start before it has finished pulling. That is worth nothing for the 81% head (already cached)
and a lot for the 19% tail (unique image per task, no reuse possible). Treat it as the tail's optimization,
and measure it before trusting it.

**Per-container run flags**, beyond the `--cpus`/`--memory` already taken from `task.toml`:
`--pids-limit`, `--ulimit nofile`, `--security-opt no-new-privileges`, dropped capabilities, and never
`-v /var/run/docker.sock`.

**Garbage collection.** `hr-agentd` prunes images LRU below 80% of the NVMe and prunes the builder cache on the
same trigger — the never-pruned local numbers (246 GB images, 74.7 GB build cache, 79% reclaimable) are what a
runner looks like after a week without this.

## Security boundaries

| boundary | mechanism |
|---|---|
| user ↔ user | separate instances. Never two tenants on one kernel |
| harness ↔ credentials | unchanged from today: the harness container sits on an `--internal` network with no route out, the proxy holds the keys and is the only egress |
| harness ↔ instance role | IMDSv2 with **hop limit 1**, so no container can read the instance's credentials. (The internal network already has no route to 169.254.169.254; hop limit is the belt to that braces) |
| run ↔ run on one host | **not yet safe — see prerequisites.** `hr-net`/`hr-int` are global names today, so a second concurrent run's harness can reach the first run's proxy by container name and spend its credentials |
| instance role | Bedrock `InvokeModel` + write to `s3://hr-runs/<run-id>/*` only, scoped by session tag |

Optional depth later: `--runtime=runsc` (gVisor) for the harness container. Not needed while the VM is
single-tenant, and it breaks some workloads.

## Reproducibility: the laptop is the runner

A run on the laptop and a run on an AWS runner go through the same `run.sh`, so they should give the same result.
Four things used to make them differ. Three are now pinned in `run.sh`; the fourth can't be:

| difference | before | now |
|---|---|---|
| **CPU architecture** | every local image was arm64 (Apple Silicon); runners are amd64 | `--platform` (default `linux/amd64`, `HR_PLATFORM` to override) on every build, pull and container, the proxy included. The Mac emulates amd64: slower, but the same images a runner builds |
| **harness commit** | the first clone was reused forever; recipes were keyed by harness name | fetch always resets to the repo's current HEAD (decision 2026-09-24: test the latest code). Recipes live in `recipes/<name>@<sha>.json` (S3 `recipes/` on AWS). The same commit reuses its recipe with no AI call |
| **AI-written Docker setup** | a new commit meant a fresh `claude -p` recipe, possibly a different Dockerfile | a new commit is analyzed **seeded with the last working recipe**, told to change only what the commit requires. The result is diffed against the seed into `recipe.diff` in the run folder |
| **unpinned build inputs** | `apt-get update`, floating base tags, `curl … \| sh` installers, unpinned npm/uv | overlays carry `hr.commit`, `hr.recipe` labels and are rebuilt only when commit, recipe or platform changes. **Still open for AWS:** build once per record and push to ECR, then pull by digest, so floating inputs resolve once per record, not once per runner |
| **the model** | Haiku at nonzero temperature; `proxy.py` request fixes since `ebede30` | irreducible. Use `k ≥ 3` and compare pass^k and flip rate, not single runs |

Every `run.json` now has a `provenance` block: platform (and whether it was emulated), Docker version, task and
overlay image ids, the recipe's hash, commit and seed, and `proxy.py`'s commit and hash. That lets two runs be
compared field by field.

**The reference result is the amd64 sweep** (decision 2026-09-24). The arm64 sweep of 2026-09-23 is a preview.
Rerun the 41 harnesses on amd64 with `k=3`, locally or on the first runner, and note per harness any outcome that
moved, with the cause: architecture, commit or proxy.

## Prerequisites in this repo

1. **Per-run networks.** `build_proxy_image` in `lib/proxy.sh` creates `hr-net` and `hr-int` once, globally. Concurrent runs on one
   host share them, so harness A can reach proxy B. Must become `hr-net-$RUN` / `hr-int-$RUN`.
2. **Proxy name length.** `hr-proxy-<run-id>-<task>` is a DNS label capped at 63 chars; run-ids get longer with
   a user prefix. Hash the suffix.
3. **`~/.aws` mount.** `start_proxy` in `lib/proxy.sh` mounts the operator's `~/.aws` into the proxy. On EC2 this becomes the
   instance role (boto3 picks it up with no code change) — but the mount must become conditional.
4. **Run folders.** `serve.py` reads `runs/` off local disk; it needs an S3-backed reader for the hosted copy.
5. **BuildKit cache mounts** in the generated overlay Dockerfile, so the pip/npm/apt downloads survive the
   overlay being rebuilt against each new task base. (Tier 1 only — tier 0 removes the rebuild entirely.)
6. **The tier-0 probe.** Export `/opt/harness` from the one overlay we already build, mount it read-only into
   each target task image, run `check_command` with `--network none`, and record the tier on the report card.
   This is a ~30-line addition to `run.sh` and it is worth more than everything else on this list.
7. **Analyzer off the run path.** Start `claude -p` when the user *imports the repo* (step 2 of the site flow),
   not when they click Run — it hides the 120 s behind the task picker.

## Cost

Compute per run at p50 with 8 containers packed on a `c6id.2xlarge` is fractions of a cent; the bill is
**idle warm capacity and the analyzer**, not the runs. Two hot instances ≈ one instance-hour price × 1460/mo,
and the analyzer is $0.6–$11 per *new* harness and $0 after the recipe is cached — so the recipe cache in S3
is the single highest-leverage line item in this document. (List prices to verify at build time.)

## Open decisions

- Do interactive sessions get a dedicated instance even at zero traffic (2 hot spares, ~$X/mo), or does the
  first user of the day wait ~90 s for a cold boot?
- Does a *public* harness's overlay in ECR get shared across users (fast, and the repo is public anyway) or
  rebuilt per user (slow, simpler story)?
- Cap on a session: tasks, wall clock, and dollars of Bedrock spend per signed-in user.
