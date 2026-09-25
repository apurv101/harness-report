# harbor.sh — everything this runner knows about a Harbor taskset: where one lives, what a task.toml says,
# which tasks a run selects, and the task's own container image.  Sourced by run.sh.

# taskset_dir <name-or-path>: the directory holding the task folders.
taskset_dir() {
  local d; for d in "$1" "$HARBOR_TASKS/datasets/$1" "$HARBOR_TASKS/hub-datasets/$1" "$HARBOR_TASKS/$1"; do
    [ -d "$d" ] && { cd "$d" && pwd; return; }; done
  die "no taskset '$1' (looked in $HARBOR_TASKS/{datasets,hub-datasets,.})"
}
# task_meta <task-dir>: one tab-separated line: difficulty category agent_timeout verifier_timeout cpus memory docker_image compose
task_meta() { python3 "$HERE/lib/task.py" "$1"; }
# list_tasks <taskset-dir> [regex]: task folder names (those with a task.toml), sorted.
list_tasks() { local d; for d in "$1"/*/; do [ -f "$d/task.toml" ] && basename "$d"; done | { [ -n "${2:-}" ] && grep -E -- "$2" || cat; } | sort; }

# task_image <task-dir> <taskset> <task>: builds environment/Dockerfile (or pulls task.toml's docker_image); echoes the tag
task_image() {
  local tdir="$1" tag="hr-task/$2:$3" prebuilt
  [ "${HR_ISOLATED_RUN:-0}" != 1 ] || tag="hr-task/$JOB_TAG/$2:$3"
  if [ -f "$tdir/environment/Dockerfile" ]; then
    docker build -q ${JOB_LABEL[@]+"${JOB_LABEL[@]}"} --platform "$PLATFORM" -t "$tag" "$tdir/environment" > "$WORK/task-build.log" 2>&1 || { tail -30 "$WORK/task-build.log" >&2; return 1; }
  else
    IFS=$'\t' read -r _ _ _ _ _ _ prebuilt _ < <(task_meta "$tdir")
    [ -n "$prebuilt" ] || { echo "task $3 has neither environment/Dockerfile nor docker_image" >&2; return 1; }
    [ "$(image_platform "$prebuilt")" = "$PLATFORM" ] || docker pull -q --platform "$PLATFORM" "$prebuilt" >/dev/null || return 1
    tag="$prebuilt"
  fi
  echo "$tag"
}

# select_tasks: resolve --tasks/--grep/--limit/--all against the taskset, drop the multi-container ones, and build
# the first task's image — the overlay is validated against it before any task runs.
# Sets TSD TS_NAME TASKS FIRST_TASK_IMG FIRST_TASK_DF.
select_tasks() {
    TSD="$(taskset_dir "$TASKSET")"; TS_NAME="$(basename "$TSD" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9_.\n-' '-')"
    stage select "taskset $TS_NAME ($TSD)"
    if [ -n "$TASK_NAMES" ]; then
      IFS=, read -r -a WANT <<< "$TASK_NAMES"
      for t in "${WANT[@]}"; do [ -f "$TSD/$t/task.toml" ] || die "no task '$t' in $TSD"; done
      CAND=("${WANT[@]}")
    else
      [ -n "$GREP$LIMIT" ] || [ "$ALL" = 1 ] || die "taskset has $(list_tasks "$TSD" | wc -l | tr -d ' ') tasks; pick with --tasks, --grep, --limit or --all"
      CAND=(); while IFS= read -r t; do CAND+=("$t"); done < <(list_tasks "$TSD" "$GREP" | { [ -n "$LIMIT" ] && head -n "$LIMIT" || cat; })
    fi
    for t in "${CAND[@]}"; do
      IFS=$'\t' read -r _ _ _ _ _ _ _ compose < <(task_meta "$TSD/$t")
      if [ -n "$compose" ]; then echo "skip   $t  (multi-container task; not supported by this runner)"; else TASKS+=("$t"); fi
    done
    [ "${#TASKS[@]}" -gt 0 ] || die "no runnable tasks selected"
    echo "tasks  ${#TASKS[@]} × k=$K:  ${TASKS[*]:0:8}$([ "${#TASKS[@]}" -gt 8 ] && echo " …")"
    echo "task image  $TS_NAME:${TASKS[0]}  (the overlay is validated against it)"
    FIRST_TASK_IMG="$(task_image "$TSD/${TASKS[0]}" "$TS_NAME" "${TASKS[0]}")" || die "could not build the task image for ${TASKS[0]}; see work/$NAME/task-build.log"
    [ -f "$TSD/${TASKS[0]}/environment/Dockerfile" ] && FIRST_TASK_DF="$(grep -v '^\s*#' "$TSD/${TASKS[0]}/environment/Dockerfile" | grep -v '^\s*$' | head -40)"
    echo "out    runs/$RUN_ID-<task>$([ "$K" -gt 1 ] && echo "-k<i>")/"
}
