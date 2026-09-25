# execute.sh — stage 6: one run.  The task image gets the overlay, the agent runs against the proxy, and for a
# Harbor task the verifier runs afterwards on tests the agent never saw.  run.json is written in three passes by
# lib/runjson.py: where the run came from, exactly what ran, and how it ended.  Sourced by run.sh.

# proxy_name <run>: the proxy's container name, which the harness resolves as a hostname, so it must be one DNS
# label (<= 63 chars) or it silently resolves to nothing and the run records 0 model calls.  Long run ids (a
# long task name after a timestamped eval id) keep their head and gain a short hash so two never collide.
proxy_name() { local n="hr-proxy-$1"
  [ "${#n}" -le 63 ] && { echo "$n"; return; }
  echo "${n:0:54}-$(printf '%s' "$1" | shasum | cut -c1-8)"; }

# run_one: uses OUT INSTR OTAG WORKDIR RUN TASKNAME TDIR AGENT_T VERIF_T RES_ARGS; sets RC REWARD SECS
run_one() {
  mkdir -p "$OUT"; [ -z "$TDIR" ] || mkdir -p "$OUT/verifier"; cp "$RECIPE" "$OUT/recipe.json"; [ "$INSTR" -ef "$OUT/task.txt" ] || cp "$INSTR" "$OUT/task.txt"
  printf '%s\n' "$RUN_CMD" > "$OUT/command.sh"
  # run.json, origin half: written before anything runs, so even a run that dies says where it came from
  python3 "$HERE/lib/runjson.py" origin "$OUT" "$RUN" "$NAME" "$OWNER/$REPO" "$COMMIT" "$TS_NAME" "$TSD" "$TASKNAME" "$MODEL" \
    "$WORKDIR" "$RUN_CMD" "$(recipe_field api_style)" "$ROUTES" "$EGRESS" "$POLICY" "$BLOCK_URLS"
  [ -f "$WORK/recipe.diff" ] && cp "$WORK/recipe.diff" "$OUT/recipe.diff"
  # run.json provenance: exactly what ran, so two runs (laptop or AWS) can be compared field by field
  python3 "$HERE/lib/runjson.py" provenance "$OUT" "$PLATFORM" "linux/$(docker version -f '{{.Server.Arch}}' 2>/dev/null)" "$(docker version -f '{{.Server.Version}}' 2>/dev/null)" \
    "${TIMG:-}" "$(docker image inspect -f '{{.Id}}' "${TIMG:-none}" 2>/dev/null || true)" "$OTAG" "$(docker image inspect -f '{{.Id}}' "$OTAG" 2>/dev/null || true)" \
    "$(recipe_hash)" "$COMMIT" "$([ "$FORCE" = 1 ] && echo "${SEED_COMMIT:-none}" || echo reused)" "$([ -f "$WORK/recipe.diff" ] && echo 1 || echo 0)" \
    "$(git -C "$HERE" log -1 --format=%H -- proxy.py 2>/dev/null || true)" "$(git -C "$HERE" diff --quiet HEAD -- proxy.py 2>/dev/null && echo 0 || echo 1)" "$HERE/proxy.py"
  emit type run run "$RUN" task "$TASKNAME"
  # the run's card, before anything runs: the site lists a run from the moment it exists, not from the moment it ends
  store publish "$OUT" --card
  stage proxy "recording → ${OUT#$HERE/}/calls.jsonl"
  start_proxy "$(proxy_name "$RUN")" "$OUT"
  local ENV_ARGS=(); while IFS= read -r kv; do ENV_ARGS+=(-e "$kv"); done < <(python3 "$HERE/lib/recipe.py" env "$RECIPE" "$PROXY_URL")
  stage run "$TASKNAME  cwd=$WORKDIR  timeout=${AGENT_T}s  $RUN_CMD"
  CUR_RUN="hr-run-$RUN"; docker rm -f "$CUR_RUN" >/dev/null 2>&1 || true
  local LOGS_MOUNT=(); [ -z "$TDIR" ] || LOGS_MOUNT=(-v "$OUT:/logs")   # Harbor: /logs/agent, /logs/verifier/reward.txt
  docker run -d ${JOB_LABEL[@]+"${JOB_LABEL[@]}"} --platform "$PLATFORM" --name "$CUR_RUN" --network "$HNET" -w "$WORKDIR" ${RES_ARGS[@]+"${RES_ARGS[@]}"} \
    -v "$OUT:/out" ${LOGS_MOUNT[@]+"${LOGS_MOUNT[@]}"} -v "$INSTR:/task/instruction.md:ro" -v "$WRAPPER:/usr/local/bin/run-harness:ro" \
    -e "PROXY_URL=$PROXY_URL" -e "HR_PATH=$(image_path "$OTAG")" -e TEST_DIR=/tests ${HENV[@]+"${HENV[@]}"} ${ENV_ARGS[@]+"${ENV_ARGS[@]}"} "$OTAG" sleep infinity >/dev/null
  local START; START=$(date +%s); set +e
  with_timeout "$AGENT_T" docker exec -w "$WORKDIR" "$CUR_RUN" bash -lc "${PRELUDE}run-harness $WORKDIR /task/instruction.md" 2>"$OUT/stderr.log" | tee "$OUT/stdout.log"
  RC=${PIPESTATUS[0]}; set -e
  SECS=$(( $(date +%s) - START ))
  { [ "$RC" = 124 ] || [ "$RC" = 142 ]; } && echo "agent hit the ${AGENT_T}s budget (recorded, not fatal)"
  REWARD=null; VRC=""
  if [ -n "$TDIR" ]; then
    # tests enter the container only now, after the agent is done, so the agent can never read them (Harbor does the same)
    stage verify "$TASKNAME  tests/test.sh  timeout=${VERIF_T}s"
    proxy_phase verify
    # The tests run the way Harbor (and `run.sh oracle`) runs them: on an open network, with none of the agent
    # phase's proxy settings.  Left in, HTTP_PROXY turns a test's own network assertions into the proxy's answers
    # — swebench psf__requests-5414 failed 15 PASS_TO_PASS tests that way (ConnectionError became a 502) for three
    # harnesses whose fix was correct.  So verify-phase traffic is not in egress.jsonl.
    [ "$EGRESS" = open ] || docker network connect "$NET" "$CUR_RUN" 2>/dev/null || true
    local UNSET=(); for v in "${HENV[@]+"${HENV[@]}"}"; do case "$v" in -e) ;; *) UNSET+=(-u "${v%%=*}") ;; esac; done
    docker cp "$TDIR/tests/." "$CUR_RUN:/tests/"
    set +e
    with_timeout "$VERIF_T" docker exec -w "$WORKDIR" "$CUR_RUN" env ${UNSET[@]+"${UNSET[@]}"} bash -lc "${PRELUDE}bash /tests/test.sh" > "$OUT/verifier/stdout.log" 2> "$OUT/verifier/stderr.log"
    VRC=$?; set -e
    REWARD="$(tr -d '[:space:]' < "$OUT/verifier/reward.txt" 2>/dev/null || true)"; REWARD="${REWARD:-null}"
    echo "reward=$REWARD  (verifier rc=$VRC)"
  fi
  finish_containers
  # run.json, result half: merged into the origin written above
  python3 "$HERE/lib/runjson.py" result "$OUT" "$RC" "$SECS" "$REWARD" "$VRC"
  emit type result run "$RUN" task "$TASKNAME" rc "$RC" reward "$REWARD" seconds "$SECS"
  # and the whole run: the card again, every model call, the egress, the verifier's tests, the files
  store publish "$OUT"
}
