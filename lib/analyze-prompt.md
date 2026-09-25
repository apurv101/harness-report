You are packaging the AI agent harness in the current directory (a fresh clone of {{REPO_URL}}) so it can run ONE task inside a Docker sandbox, with all its model calls going through a recording proxy. Read the repo (README, manifests, the CLI entrypoint, the model/provider client code) and return the recipe as JSON matching the schema.

THE PROXY CONTRACT
- The proxy is reachable from the container at $PROXY_URL (literal string; it is substituted at run time). It speaks BOTH
  the OpenAI chat-completions API ($PROXY_URL/v1/chat/completions, list at $PROXY_URL/v1/models) and the Anthropic
  messages API ($PROXY_URL/v1/messages). Streaming and tool calling work on both. Any API key string is accepted.
- The proxy routes each call by the model name the harness sends: it may serve that exact model or swap it for another.
  So keep the harness's own default model name(s) where it has them (a harness that uses several models for different
  roles must keep sending distinct names); only if it has none, pick a real model name it accepts (e.g. for litellm use
  an 'openai/<name>' or 'anthropic/<name>' prefix so the base URL applies; for the Anthropic SDK a claude name).
- The harness must NOT need any cloud credentials or network access other than the proxy at run time.
  Typical env: OPENAI_BASE_URL=$PROXY_URL/v1 + OPENAI_API_KEY=proxy, or ANTHROPIC_BASE_URL=$PROXY_URL + ANTHROPIC_API_KEY=proxy,
  plus whatever variable this harness uses to choose the model, plus anything that skips first-run wizards, telemetry,
  confirmations, or interactive prompts (stdin is NOT a tty).

THE OVERLAY DOCKERFILE
- The Dockerfile is an OVERLAY: its first two instructions MUST be 'ARG BASE=<base_image>' and 'FROM ${BASE}'. We build it
  on top of images chosen at build time: your base_image for ad-hoc tasks, and benchmark task images (Debian/Ubuntu
  userland with apt-get, e.g. buildpack-deps:jammy or python:3.x-slim, which carry their own python/node/toolchains that
  the task's tests depend on). So: assume only a Debian/Ubuntu base with apt-get; NEVER rely on or change the base
  image's python/node/packages. Install the harness runtime SELF-CONTAINED under /opt/harness (python: install uv into
  /opt/harness, 'uv python install <ver>' with UV_PYTHON_INSTALL_DIR under /opt/harness, then install the harness with
  uv into a venv or tool dir there; node: unpack an official node tarball into /opt/harness/node) and put its bin
  directories on PATH with ENV PATH=/opt/harness/bin:...:$PATH. apt-get only what is missing (ca-certificates, curl, git...).
- Build context is the repo root: COPY the source in (e.g. to /opt/harness/src) and install it from there so the
  entrypoint is the harness's own CLI. Do not bake in secrets. Do not run the harness during the build. The harness is
  never modified. Do not set WORKDIR to the harness source; the run happens in the task's directory.

THE RUN COMMAND
- bash, run inside the container via 'bash -lc' with the env above, cwd = the task's working directory (the harness must
  read and edit files THERE), and the task text in $TASK. It must run exactly one task non-interactively through the
  harness's own CLI entrypoint and exit when done. If the harness can write its own trajectory/log/history to a path,
  write it under /out/ (mounted from the host). Use $TASK unquoted-safe: e.g. -t "$TASK". No 'cd' into the harness source.
- check_command: something fast that proves the install works without calling a model (e.g. the CLI --help).

Repository tree (2 levels):
