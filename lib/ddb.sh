# ddb.sh — the laptop's DynamoDB, and the `run.sh ddb` subcommand that drives it.  Sourced by run.sh.
#
#   ./run.sh ddb start     DynamoDB Local in docker on :8001, then create the table if it isn't there
#   ./run.sh ddb stop      stop the container; its data stays
#   ./run.sh ddb reset     delete the container and every row in it ( `ddb start && ddb sync` rebuilds)
#   ./run.sh ddb status    what is in the table            ./run.sh ddb logs   tail the container
#   ./run.sh ddb table     create the table                ./run.sh ddb sync [--grep re]   folders → table
#   ./run.sh ddb runs | run <id> | recipes | harness <name>     read it back as JSON
#
# The container is the database: DynamoDB Local with -sharedDb writes one file in its own filesystem, so `reset`
# is `docker rm`.  That is the right shape here because the table is a DERIVED index — the run folders are the
# record, and `ddb sync` rebuilds every row from them.
#
# Port 8001, not 8000: accounting-harness runs its own DynamoDB Local on 8000 and both should be able to be up.
# The container ops always mean this local instance; table/sync/status/reads go wherever HR_DDB, HR_DDB_ENDPOINT
# and HR_TABLE point (lib/ddb.py resolves it, and every one of them prints which table it used).

DDB_NAME="${HR_DDB_NAME:-harness-report-ddb}"
DDB_PORT="${HR_DDB_PORT:-8001}"
DDB_IMAGE="amazon/dynamodb-local:latest"

ddb_exists()  { docker ps -a --format '{{.Names}}' | grep -qx "$DDB_NAME"; }
ddb_running() { docker ps    --format '{{.Names}}' | grep -qx "$DDB_NAME"; }
# store.py with no HR_DDB set would talk to AWS; the container ops are about the laptop, so they say so.
ddb_local()   { HR_DDB="${HR_DDB:-local}" python3 "$HERE/lib/store.py" "$@"; }

ddb_wait() {   # the port is bound before the JVM listens; the first call after `docker run` would race it
  local i
  for i in $(seq 1 40); do
    curl -s -o /dev/null "http://127.0.0.1:$DDB_PORT" && return 0
    sleep 0.5
  done
  echo "the container is up but nothing answered on :$DDB_PORT — ./run.sh ddb logs" >&2; return 1
}

ddb_start() {
  docker info >/dev/null 2>&1 || die "Docker is not running"
  if ddb_running; then echo "$DDB_NAME already on :$DDB_PORT"
  elif ddb_exists; then docker start "$DDB_NAME" >/dev/null; echo "started $DDB_NAME on :$DDB_PORT (last run's data is still there)"
  else
    lsof -nP -iTCP:"$DDB_PORT" -sTCP:LISTEN >/dev/null 2>&1 && \
      die "port $DDB_PORT is taken (another repo's DynamoDB Local?) — HR_DDB_PORT=8002 ./run.sh ddb start, and HR_DDB_ENDPOINT=http://127.0.0.1:8002 in .env"
    # -sharedDb is the whole flag list's point: without it DynamoDB Local keeps a separate set of tables per
    # (access key, region), so a table created by one process is invisible to another that signed differently.
    docker run -d --name "$DDB_NAME" -p "$DDB_PORT":8000 "$DDB_IMAGE" -jar DynamoDBLocal.jar -sharedDb >/dev/null \
      || die "could not start $DDB_IMAGE"
    echo "created $DDB_NAME on :$DDB_PORT"
  fi
  ddb_wait || return 1
  ddb_local table
  grep -q '^HR_DDB=' "$HERE/.env" 2>/dev/null || echo "note: add HR_DDB=local to .env so run.sh, serve.py and store.py all use it"
}

cmd_ddb() {
  local sub="${1:-status}"; shift || true
  case "$sub" in
    start)  ddb_start ;;
    stop)   ddb_exists && { docker stop "$DDB_NAME" >/dev/null; echo "stopped $DDB_NAME (data kept)"; } || echo "$DDB_NAME is not there" ;;
    reset)  ddb_exists && { docker rm -f "$DDB_NAME" >/dev/null; echo "removed $DDB_NAME and every row in it"; } || echo "$DDB_NAME is not there"
            echo "rebuild:  ./run.sh ddb start && ./run.sh ddb sync" ;;
    logs)   exec docker logs -f "$DDB_NAME" ;;
    table|sync|status|target|runs|run|recipes|harness|publish|recipe|eval)
            exec python3 "$HERE/lib/store.py" "$sub" "$@" ;;
    *)      die "run.sh ddb: start | stop | reset | logs | table | sync | status | target | runs | run <id> | recipes | harness <name>" ;;
  esac
}

# store <store.py args…>: publish into the table, if there is one.  Configured means HR_DDB, HR_DDB_ENDPOINT or
# HR_TABLE is set (.env) — with none of them, a run publishes nothing rather than groping for a table in AWS.
# Never fatal, for the same reason emit() is never fatal: the index is a copy, the run folder is the record.
store() {
  [ -n "${HR_DDB:-}${HR_DDB_ENDPOINT:-}${HR_TABLE:-}" ] || return 0
  python3 "$HERE/lib/store.py" "$@" || echo "run.sh: the run store did not take that write (the run folder is intact)" >&2
}
