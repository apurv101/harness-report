# report.sh — the three read-only subcommands (`tasks`, `runs`, `view`) and the end-of-sweep table.
# Each of them only reads what a run already wrote; the work is in lib/report.py.  Sourced by run.sh.

# run.sh tasks <taskset> [--grep re]: every task in a taskset, with its difficulty and category.
cmd_tasks() {
  local TS="${1:?usage: run.sh tasks <taskset> [--grep re]}" RE="" TSD N=0 t diff cat compose
  [ "${2:-}" = --grep ] && RE="${3:?}"
  TSD="$(taskset_dir "$TS")"
  while IFS= read -r t; do
    IFS='|' read -r diff cat _ _ _ _ _ compose < <(task_meta "$TSD/$t")
    printf '%-60s %-8s %-24s %s\n' "$t" "$diff" "$cat" "${compose:+(multi-container, Harbor backend)}"; N=$((N+1))
  done < <(list_tasks "$TSD" "$RE")
  echo "$N tasks in $TSD"
}
# run.sh runs [--grep re]: one line per run folder, read back out of each run.json.
cmd_runs() { local RE=""; [ "${1:-}" = --grep ] && RE="${2:?}"; exec python3 "$HERE/lib/report.py" runs "$HERE/runs" "$RE"; }
# run.sh view runs/<run-id>: the recorded model calls as a conversation.  A path to a file inside the run works too.
cmd_view() { local D="${1:?usage: run.sh view runs/<run-id>}"; [ -f "$D/calls.jsonl" ] || D="$(dirname "$D")"
  exec python3 "$HERE/lib/report.py" view "$D/calls.jsonl"; }
# print_summary <batch.jsonl> <k>: the task × k reward table at the end of a Harbor sweep.
print_summary() { python3 "$HERE/lib/report.py" summary "$1" "$2"; }
