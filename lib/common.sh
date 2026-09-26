# common.sh — the small things every stage uses: events for the UI, fatal errors, stage timing, a portable
# timeout, and the three docker image lookups.  Sourced by run.sh, which sets HERE (the repo root) and T0.

# emit key value ...: with $HR_EVENTS set (serve.py sets it for runs started from the site), append one JSON event per
# call to that file — stages, the recipe decision, each task's run folder and result, errors. The terminal output is
# unchanged; the events are what the UI reads to show progress.
emit() {
  [ -n "${HR_EVENTS:-}" ] || return 0
  python3 "$HERE/lib/events.py" "$HR_EVENTS" "$@" || true
}
die() { echo "run.sh: $*" >&2; emit type error msg "$*"; exit 2; }
# help: the header comment of run.sh is the usage message, so the two can never drift apart.
help() { awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$HERE/run.sh"; }
# stage <name> [message]: the one-line banner between pipeline stages, and the event the UI draws progress from.
stage() { echo; echo "━━ [$1] $(( $(date +%s) - T0 ))s  ${2:-}"; emit type stage stage "$1" t "$(( $(date +%s) - T0 ))" msg "${2:-}"; }
# portable timeout: coreutils timeout / gtimeout if present, else perl alarm (exit 142 on expiry)
with_timeout() { local s="$1"; shift
  if command -v timeout >/dev/null 2>&1; then timeout "$s" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then gtimeout "$s" "$@"
  else perl -e 'alarm shift; exec @ARGV' "$s" "$@"; fi; }
# Every command in a sandbox runs through `bash -lc` (so the image's profile.d scripts apply). Debian's /etc/profile
# resets PATH, which would hide the overlay's /opt/harness/bin; HR_PATH carries the image's PATH and PRELUDE restores it.
PRELUDE='[ -n "${HR_PATH:-}" ] && export PATH="$HR_PATH"; '
image_path() { docker image inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$1" | sed -n 's/^PATH=//p' | head -1; }
image_platform() { docker image inspect -f '{{.Os}}/{{.Architecture}}' "$1" 2>/dev/null || true; }
# uses_bedrock: MODEL or any ROUTES target goes to Bedrock (so the proxy needs AWS credentials)
uses_bedrock() { local t; for t in "$MODEL" $(printf '%s' "$ROUTES" | tr ',' '\n' | sed -n 's/^[^=]*=//p'); do
  case "$t" in anthropic|anthropic/*|openai|openai/*) ;; *) return 0 ;; esac; done; return 1; }
image_label() { docker image inspect -f "{{index .Config.Labels \"$2\"}}" "$1" 2>/dev/null || true; }
