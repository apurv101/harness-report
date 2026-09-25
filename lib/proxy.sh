# proxy.sh — stage 5: the recording proxy the harness talks to instead of a model provider.  One hr-proxy image
# per invocation, one container per run, sitting on both networks so the sandbox's only way out goes through it.
# Sourced by run.sh, which installs finish_containers as its EXIT trap.

# build_proxy_image: the two networks and the hr-proxy image, built once for the whole invocation.
# Sets CONTROL_TOKEN (lets run.sh, and not the harness, open the verify phase) and the CUR_* container handles.
build_proxy_image() {
  NET=hr-net; INT=hr-int; PROXY_IMAGE=hr-proxy
  if [ "${HR_ISOLATED_RUN:-0}" = 1 ]; then
    NET="hr-net-$RUN_ID"; INT="hr-int-$RUN_ID"; PROXY_IMAGE="hr-proxy:$RUN_ID"
  fi
  docker network inspect "$NET" >/dev/null 2>&1 || docker network create ${JOB_LABEL[@]+"${JOB_LABEL[@]}"} "$NET" >/dev/null
  # hr-int has no route out: a harness container on it reaches the world only through the proxy, which sits on both
  docker network inspect "$INT" >/dev/null 2>&1 || docker network create --internal ${JOB_LABEL[@]+"${JOB_LABEL[@]}"} "$INT" >/dev/null
  CONTROL_TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"   # lets run.sh (not the harness) open the verify phase
  PCTX="$WORK/.proxy-ctx"; mkdir -p "$PCTX"; cp "$HERE/proxy.py" "$HERE/policy.py" "$PCTX/"
  printf 'FROM python:3.12-slim\nRUN pip install -q --root-user-action=ignore boto3 cryptography\nCOPY proxy.py policy.py /\nCMD ["python3","-u","/proxy.py"]\n' > "$PCTX/Dockerfile"
  docker build -q ${JOB_LABEL[@]+"${JOB_LABEL[@]}"} --platform "$PLATFORM" -t "$PROXY_IMAGE" "$PCTX" >/dev/null
  CUR_PROXY=""; CUR_RUN=""; CUR_OUT=""
}
# finish_containers: the EXIT trap — the run's proxy log is saved before both containers are removed.
finish_containers() {
  [ -n "$CUR_RUN" ] && { docker rm -f "$CUR_RUN" >/dev/null 2>&1 || true; }
  [ -n "$CUR_PROXY" ] && { docker logs "$CUR_PROXY" > "$CUR_OUT/proxy.log" 2>&1 || true; docker rm -f "$CUR_PROXY" >/dev/null 2>&1 || true; }
  CUR_RUN=""; CUR_PROXY=""
}
start_proxy() {  # $1 = container name, $2 = out dir → sets PROXY_URL
  CUR_PROXY="$1"; CUR_OUT="$2"
  docker rm -f "$1" >/dev/null 2>&1 || true
  # keys are passed by name (-e VAR), so their values never appear in the docker command line
  local PENV=() v; for v in AWS_PROFILE AWS_EC2_METADATA_DISABLED ANTHROPIC_API_KEY ANTHROPIC_BASE_URL OPENAI_API_KEY OPENAI_BASE_URL; do
    [ -n "${!v:-}" ] && { export "${v?}"; PENV+=(-e "$v"); }; done
  # Harbor: the task's tests (and environment, to discount lines it already holds) go to the PROXY only, for the
  # verifier_leak check; the harness container never gets them before the verify stage
  local TMOUNT=(); if [ -n "${TDIR:-}" ] && [ -d "$TDIR/tests" ]; then TMOUNT+=(-v "$TDIR/tests:/hr/tests:ro" -e TESTS_DIR=/hr/tests)
    [ -d "$TDIR/environment" ] && TMOUNT+=(-v "$TDIR/environment:/hr/env:ro" -e ENV_DIR=/hr/env); fi
  local AWSMOUNT=()
  if uses_bedrock; then
    if [ -n "${HR_PROXY_CREDENTIALS_DIR:-}" ]; then
      AWSMOUNT=(-v "$HR_PROXY_CREDENTIALS_DIR:/hr/aws:ro" -e AWS_PROFILE=hr-model -e AWS_CONFIG_FILE=/hr/aws/config -e AWS_EC2_METADATA_DISABLED=true)
    else AWSMOUNT=(-v "$HOME/.aws:/root/.aws:ro"); fi
  fi
  docker run -d ${JOB_LABEL[@]+"${JOB_LABEL[@]}"} --platform "$PLATFORM" --name "$1" --network "$NET" ${AWSMOUNT[@]+"${AWSMOUNT[@]}"} -v "$2:/out" \
    -e "MODEL=$MODEL" -e "ROUTES=$ROUTES" -e "AWS_REGION=$AWS_REGION" -e "AWS_DEFAULT_REGION=$AWS_REGION" -e LOG=/out/calls.jsonl \
    -e "EGRESS=$EGRESS" -e "POLICY=$POLICY" -e "BLOCK_URLS=$BLOCK_URLS" -e "CONTROL_TOKEN=$CONTROL_TOKEN" -e "SELF_HOSTS=$1" \
    ${PENV[@]+"${PENV[@]}"} ${TMOUNT[@]+"${TMOUNT[@]}"} "$PROXY_IMAGE" >/dev/null
  [ "$EGRESS" = open ] || docker network connect "$INT" "$1"
  local i; for i in $(seq 1 30); do
    docker exec "$1" python3 -c "import urllib.request;urllib.request.urlopen('http://localhost:4000/health',timeout=2)" 2>/dev/null && break
    sleep 1; [ "$i" = 30 ] && { docker logs "$1"; die "proxy did not come up"; }
  done
  PROXY_URL="http://$1:4000"
  # what the harness container gets: its network, and the env that sends every client through the egress proxy
  HNET="$NET"; HENV=()
  if [ "$EGRESS" != open ]; then
    HNET="$INT"; local v; for v in HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy; do HENV+=(-e "$v=http://$1:3128"); done
    HENV+=(-e "NO_PROXY=$1,localhost,127.0.0.1" -e "no_proxy=$1,localhost,127.0.0.1" -e NODE_USE_ENV_PROXY=1)
    if [ "$EGRESS" = inspect ]; then for v in SSL_CERT_FILE REQUESTS_CA_BUNDLE NODE_EXTRA_CA_CERTS CURL_CA_BUNDLE GIT_SSL_CAINFO; do HENV+=(-e "$v=/out/hr-ca.pem"); done; fi
  fi
}
proxy_phase() {  # $1 = agent | verify
  [ "$EGRESS" = open ] || docker exec -e "T=$CONTROL_TOKEN" -e "P=$1" "$CUR_PROXY" python3 -c "import os,urllib.request
urllib.request.urlopen(urllib.request.Request('http://localhost:4000/_hr/phase', data=('{\"phase\":\"'+os.environ['P']+'\"}').encode(), headers={'X-HR-Token': os.environ['T']}), timeout=5)" >/dev/null
}
