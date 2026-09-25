#!/usr/bin/env python3
"""store.py — everything about a run, in one DynamoDB table.

A run folder is the record of a run; this is that record as rows, so a screen can ask for exactly the piece it is
drawing instead of a server walking 600 MB of run folders on every request.  One table, generic `pk`/`sk`, the same
single-table shape the accounting harness uses next door.

    pk                        sk                      what
    ------------------------- ----------------------- ---------------------------------------------------------
    RUNLIST                   RUN#<run-id>            the run card: all of run.json, plus the test tally
    RUN#<run-id>              META                     the same card, for a read that already knows the run id
    RUN#<run-id>              CALL#<0000000001>        one model call, as the proxy recorded it
    RUN#<run-id>              EGRESS#<0000000001>      one outbound connection the sandbox made
    RUN#<run-id>              FILE#<path in folder>    one file: its size, and its text when it is text and small
    RUN#<run-id>              MANIFEST                 every file in the folder, name and size
    RUN#<run-id>              TESTS                    the per-test breakdown, with sources and tracebacks
    RECIPELIST                RECIPE#<name>@<commit>   the recipe card
    RECIPE#<name>@<commit>    META                     the recipe itself: base image, Dockerfile, commands, env
    EVALLIST                  EVAL#<eval-id>           an evaluation started from the site
    EVAL#<eval-id>            META                     eval.json, and run.sh's console output
    EVAL#<eval-id>            EVENT#<0000000001>       one stage event run.sh emitted for it
    HARNESSLIST               HARNESS#<name>           the harness card: repo, latest recipe, runs, passes, per-task results
    HARNESS#<name>            META                     the same card
    HARNESS#<name>            PROFILE                  what the harness is for (lib/profile.py): use case, domains, languages
    HARNESS#<name>            RECS                     the tests to run next, ranked (lib/recommend.py)
    TASKSETLIST               TASKSET#<taskset>        the taskset card: size, domain, languages, catalog provenance
    TASKSET#<taskset>         META                     the same card
    TASKSET#<taskset>         TASK#<task>              the task card: task.toml, instruction.md (cut at 16k), runnable, oracle,
                                                       and `results` — every harness's runs on it, folded in by refresh_task
    RUNNABLE                  TASK#<taskset>/<task>    the same card, for the tasks the site may start (lib/tasks.py)

Index `harness` (gsi1pk/gsi1sk) carries the cards a second time under `HARNESS#<name>`, sorted
`RUN#<started>#<run-id>` and `RECIPE#<commit>` — every run and every recipe of one harness, in one query.
Index `task` (gsi2pk/gsi2sk) carries each Harbor run card under `TASK#<taskset>/<task>`, sorted
`RUN#<started>#<run-id>` — every harness's runs on one task, in one query.

The task corpus is the one thing here that is not derived from a folder in this repo: `sync --tasks` reads it
from $HARBOR_TASKS on the runner's disk, because the site has no disk to read it from.

Three rules, all inherited from the sibling repo's store and all load-bearing:

* **No UpdateItem.** Every row is re-put whole.  One writer owns a partition (the run that is producing it), so
  there is nothing to merge, and the IAM a real deployment needs stays Query/GetItem/PutItem/BatchWriteItem.
* **The index row carries the whole card.**  The runs page renders from one Query, not 67 GetItems.
* **Sequence sort keys are zero-padded to 10 digits**, and `META`/`MANIFEST`/`TESTS` sort outside those ranges, so
  a `begins_with(sk, "CALL#")` can never sweep up the metadata.

Big things stay files.  A run folder can be 150 MB (one harness ships a whole Node install into `/out`), and a
DynamoDB item is capped at 400 KB, so what goes in a row is every *fact* about the run — plus the text of the files
a person reads, inlined while they are small.  Anything bigger keeps its size and path and is served from the
folder (from S3, once runs land there: RUN-PLANE.md).  A row that had to be cut says so in `truncated`.

    lib/store.py table                      create the table if it isn't there
    lib/store.py target                     print where the data goes, and whether it is reachable
    lib/store.py publish <run-dir> [--card] the run (--card: only the card, before the agent starts)
    lib/store.py recipe <recipes/x@sha.json>
    lib/store.py eval <eval-id>             an evaluation the site started, with its events and console log
    lib/store.py sync [--grep re] [--runs|--recipes|--evals|--tasks|--harnesses] [--quiet]
    lib/store.py status                     what is in the table
    lib/store.py runs [--limit n] | run <run-id> | recipes | harness <name>

`sync` rebuilds the table from the folders, so the table is a derived index: losing it costs one command.
"""
import argparse, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ddb, verifier                                                   # noqa: E402

ROOT = os.path.dirname(HERE)
RUNS = os.path.join(ROOT, "runs")
RECIPES = os.path.join(ROOT, "recipes")
EVALS = os.path.join(ROOT, "evals")

GSI, TASK_GSI = "harness", "task"
RUNLIST, RECIPELIST, EVALLIST = "RUNLIST", "RECIPELIST", "EVALLIST"
HARNESSLIST, TASKSETLIST, RUNNABLE = "HARNESSLIST", "TASKSETLIST", "RUNNABLE"

# The same five files serve.py inlines into a run bundle, and the same definition of "core".
TEXT_FILES = ("task.txt", "command.sh", "stdout.log", "stderr.log", "proxy.log")
CORE = TEXT_FILES + ("run.json", "recipe.json", "calls.jsonl")
BUNDLE_KEYS = {f: f.split(".")[0] for f in TEXT_FILES}                 # stdout.log -> stdout

ITEM_BUDGET = 330_000      # bytes of JSON per item; DynamoDB's hard limit is 400 KB, and attribute names count
TEXT_INLINE = 200_000      # a file's text goes in the row below this size; above it, head and tail
FILE_ROWS = 400            # rows per run for individual files — two runs hold >5,000 files of harness home dir
MANIFEST_ROWS = 1000       # entries in the manifest list
TEXTY = {".log", ".txt", ".json", ".jsonl", ".md", ".sh", ".yaml", ".yml", ".py", ".patch", ".diff", ".traj",
         ".pred", ".history", ".csv", ".toml", ".ini", ".cfg", ".env", ".ndjson", ".xml", ".ts", ".js"}
PAD = 10


# ------------------------------------------------------------------ keys (the only place a key is built)
def run_sk(n, kind): return f"{kind}#{str(n).zfill(PAD)}"
def run_pk(rid): return f"RUN#{rid}"
def recipe_id(name, commit): return f"{name}@{commit}"
def recipe_pk(rid): return f"RECIPE#{rid}"
def eval_pk(eid): return f"EVAL#{eid}"
def harness_pk(name): return f"HARNESS#{name}"
def taskset_pk(ts): return f"TASKSET#{ts}"
def harness_name(repo):
    """The harness name run.sh derives from a GitHub owner/repo (run.sh: NAME=...), so a harness's cards can be
    found from its repo before it has ever been run."""
    return re.sub(r"[^a-z0-9.\-]", "-", repo.replace("/", "-").lower())
def task_key(ts, task): return f"TASK#{ts}/{task}"


# ------------------------------------------------------------------ reading a run folder
def read(path, default=None):
    try:
        with open(path, encoding="utf-8", errors="replace") as f: return f.read()
    except OSError: return default


def load_json(path):
    s = read(path)
    if s is None: return None
    try: return json.loads(s)
    except ValueError: return {"_parse_error": True, "_raw": s}


def jsonl(path):
    """Every parseable line of a .jsonl, and the count of the ones that were not."""
    out, bad = [], 0
    for line in (read(path) or "").splitlines():
        if not line.strip(): continue
        try: out.append(json.loads(line))
        except ValueError: bad += 1
    return out, bad


def action(call):
    """The last tool call in a recorded response, as one short line: `bash: pytest -q`.  It is what the runs list
    and the live counter show as "what the agent is doing", so both read it from here."""
    resp = call.get("response") or {}
    uses = []
    for ch in resp.get("choices") or []:
        for tc in (ch.get("message") or {}).get("tool_calls") or []:
            fn = tc.get("function") or {}
            try: args = json.loads(fn.get("arguments") or "{}")
            except ValueError: args = fn.get("arguments")
            uses.append((fn.get("name"), args))
    for b in resp.get("content") or []:
        if isinstance(b, dict) and b.get("type") == "tool_use": uses.append((b.get("name"), b.get("input")))
    if not uses: return None
    name, args = uses[-1]
    if isinstance(args, dict):
        args = next((args[k] for k in ("command", "cmd", "path", "file_path", "query") if isinstance(args.get(k), str)), json.dumps(args))
    one = " ".join(str(args or "").split())
    return f"{name}: {one[:120]}" + ("…" if len(one) > 120 else "")


def fit(item, fields=("request", "response", "text")):
    """Cut an item down to one DynamoDB item.  The long JSON payloads are trimmed longest-first, and the row says
    which ones lost bytes — a truncated call is still worth having, a rejected write is not."""
    size = len(json.dumps(item))
    if size <= ITEM_BUDGET: return item
    cut = []
    for f in sorted([f for f in fields if isinstance(item.get(f), str)], key=lambda f: -len(item[f])):
        over = len(json.dumps(item)) - ITEM_BUDGET
        if over <= 0: break
        keep = max(0, len(item[f]) - over - 200)
        item[f] = item[f][:keep] + f"\n…[{len(item[f]) - keep} bytes not stored; read the file in the run folder]"
        cut.append(f)
    item["truncated"] = cut
    return item


def text_of(path, size):
    """A file's text for its row: whole while it is small, otherwise the head and the tail, which is where the
    interesting part of a log is."""
    if size <= TEXT_INLINE: return read(path), None
    s = read(path) or ""
    half = TEXT_INLINE // 2
    return s[:half] + f"\n…[{len(s) - 2 * half} bytes not stored]…\n" + s[-half:], {"bytes": size, "kept": 2 * half}


def is_text(name, size):
    if os.path.splitext(name)[1].lower() in TEXTY: return True
    return "." not in os.path.basename(name) and size <= TEXT_INLINE


# ------------------------------------------------------------------ a run folder, as rows
def card_of_run(d, rid):
    """The run card: run.json as written, plus what serve.py adds on top of it, plus a status a query can filter
    on.  Both the list row and the META row are this same dict — the runs page renders from one Query."""
    rj = load_json(os.path.join(d, "run.json")) or {}
    calls, _ = jsonl(os.path.join(d, "calls.jsonl"))
    card = {"run": rid, "has_run_json": bool(rj), **rj}
    if card.get("calls") is None: card["calls"] = len(calls)
    card["tests"] = verifier.parse(d)
    card["status"] = "done" if rj.get("finished") else "running"
    card["last_action"] = next((action(c) for c in reversed(calls) if action(c)), None)
    return card


def items_of_run(d, card_only=False):
    """Every row for one run folder.  card_only is the write that happens before the agent starts, so a run shows
    up on the site the moment it exists."""
    rid = os.path.basename(d.rstrip("/"))
    card = card_of_run(d, rid)
    harness = (card.get("harness") or {}).get("name") or "unknown"
    # pk/sk go on AFTER the card is spread in: a card read back out of the table carries its own keys, and both
    # writes would otherwise land on the same row, leaving the list silently stale.
    t = card.get("task") or {}
    by_task = {"gsi2pk": task_key(t["taskset"], t["name"]), "gsi2sk": f"RUN#{card.get('started') or ''}#{rid}"} \
        if card.get("kind") == "harbor" and t.get("taskset") and t.get("name") else {}
    items = [{**card, "pk": RUNLIST, "sk": f"RUN#{rid}", **by_task,
              "gsi1pk": harness_pk(harness), "gsi1sk": f"RUN#{card.get('started') or ''}#{rid}"},
             {**card, "pk": run_pk(rid), "sk": "META"}]
    if card_only: return items

    calls, bad = jsonl(os.path.join(d, "calls.jsonl"))
    for n, c in enumerate(calls, 1):
        # The row is the recorded call, field for field — a reader of the table must see the same call a reader of
        # calls.jsonl sees, so nothing is renamed, flattened or summarised here.  Two changes only: the two big
        # payloads become JSON text, because nothing queries inside them, DynamoDB refuses maps nested deeper than
        # 32 levels and a string costs one marshal instead of thousands; and `action` is added, which is the one
        # line the runs list shows for "what the agent did".
        items.append(fit({**c, "pk": run_pk(rid), "sk": run_sk(c.get("n") or n, "CALL"), "n": c.get("n") or n,
                          "action": action(c), "request": json.dumps(c.get("request")),
                          "response": json.dumps(c.get("response"))}))
    if bad: items[0]["calls_unparsed"] = items[1]["calls_unparsed"] = bad

    egress, _ = jsonl(os.path.join(d, "egress.jsonl"))
    for n, e in enumerate(egress, 1):
        items.append({**e, "pk": run_pk(rid), "sk": run_sk(e.get("n") or n, "EGRESS")})

    full = verifier.parse(d, full=True)
    if full: items.append(fit({"pk": run_pk(rid), "sk": "TESTS", **full, "cases": json.dumps(full.get("cases"))}))

    # The folder, by name — the same order and the same three fields serve.py's file list has, so a page rendering
    # from the table and a page rendering from the folder show the same list.
    found = []
    for root, _, fs in os.walk(d):
        for f in fs:
            p = os.path.join(root, f); rel = os.path.relpath(p, d)
            try: found.append((rel, os.path.getsize(p)))
            except OSError: pass          # a harness can leave a dangling symlink in /out
    found.sort()
    manifest = [{"name": rel, "bytes": n, "core": rel in CORE} for rel, n in found[:MANIFEST_ROWS]]
    rows = 0
    for rel, size in found:
        # A row per file, except in the two runs that shipped a whole Node install into /out: there, the top level
        # and the verifier's output still get rows, and the rest is in the manifest with its size.
        top = os.sep not in rel
        if rows >= FILE_ROWS and not top and not rel.startswith("verifier" + os.sep): continue
        row = {"pk": run_pk(rid), "sk": f"FILE#{rel}", "name": rel, "bytes": size, "core": rel in CORE, "top_level": top}
        if is_text(rel, size):
            row["text"], cut = text_of(os.path.join(d, rel), size)
            if cut: row["truncated"] = cut
        items.append(fit(row)); rows += 1
    items.append({"pk": run_pk(rid), "sk": "MANIFEST", "files": manifest, "file_rows": rows,
                  "files_omitted": len(found) - len(manifest), "bytes_total": sum(n for _, n in found),
                  # An empty verifier/ is a fact too: it means the verifier ran and wrote nothing, which is not the
                  # same as a prompt run that has no verifier at all, and no file row can say it.
                  "has_verifier": os.path.isdir(os.path.join(d, "verifier"))})
    return items


# ------------------------------------------------------------------ a recipe, as rows
RECIPE_FILE = re.compile(r"^(?P<name>.+)@(?P<commit>[0-9a-f]{7,40})\.json$")


def items_of_recipe(path):
    m = RECIPE_FILE.match(os.path.basename(path))
    if not m: raise SystemExit(f"not a recipe file name (<name>@<commit>.json): {path}")
    name, commit = m["name"], m["commit"]
    r = load_json(path) or {}
    rid = recipe_id(name, commit)
    import hashlib
    card = {"recipe": rid, "harness": name, "commit": commit, "file": os.path.relpath(path, ROOT),
            "bytes": os.path.getsize(path), "sha256": hashlib.sha256(open(path, "rb").read()).hexdigest()[:16],
            "base_image": r.get("base_image"), "api_style": r.get("api_style"), "workdir": r.get("workdir"),
            "summary": r.get("summary"), "env_names": [e.get("name") for e in r.get("env") or []]}
    gsi = {"gsi1pk": harness_pk(name), "gsi1sk": f"RECIPE#{commit}"}
    return [{**card, **gsi, "pk": RECIPELIST, "sk": f"RECIPE#{rid}"},
            fit({**card, **gsi, "pk": recipe_pk(rid), "sk": "META", "dockerfile": r.get("dockerfile"),
                 "run_command": r.get("run_command"), "check_command": r.get("check_command"),
                 "env": r.get("env"), "notes": r.get("notes"), "recipe": json.dumps(r)}, ("recipe", "dockerfile"))]


# ------------------------------------------------------------------ an evaluation the site started, as rows
def eval_card(ev, n_events=0):
    """The two rows that describe an evaluation — the list row and the META row — built from the record itself.

    Separate from items_of_eval because the API has no disk: it creates an evaluation and publishes this much
    before any runner has seen it, so the page can show a queued run that has not started."""
    eid = ev["id"]
    card = {**{k: v for k, v in ev.items() if k != "pid"}, "eval": eid, "events": n_events}
    return [{**card, "pk": EVALLIST, "sk": f"EVAL#{eid}"}, fit({**card, "pk": eval_pk(eid), "sk": "META"}, ("console",))]


def items_of_eval(eid):
    """Everything in one evals/<id> folder: the same two card rows, plus the console text and one row per event.
    This is the runner's side — it has the folder; the API only ever has the record."""
    d = os.path.join(EVALS, eid)
    ev = load_json(os.path.join(d, "eval.json")) or {}
    events, _ = jsonl(os.path.join(d, "events.jsonl"))
    console = os.path.join(d, "console.log")
    listed, meta = eval_card({**ev, "id": eid}, len(events))
    if os.path.exists(console):
        meta["console"], cut = text_of(console, os.path.getsize(console))
        if cut: meta["truncated"] = cut
        meta = fit(meta, ("console",))
    items = [listed, meta]
    for n, e in enumerate(events, 1):
        items.append({**e, "pk": eval_pk(eid), "sk": run_sk(n, "EVENT")})
    return items


# ------------------------------------------------------------------ writing
def _gsi(name, pk, sk):
    return {"IndexName": name, "Projection": {"ProjectionType": "ALL"},
            "KeySchema": [{"AttributeName": pk, "KeyType": "HASH"}, {"AttributeName": sk, "KeyType": "RANGE"}]}


def create_table(name=None):
    """Create the table, or add whichever index an older table is missing (the `task` index came later)."""
    import time
    t = ddb.table(name)
    status = ddb.exists(name)
    if status:
        have = ddb.indexes(name)
        if TASK_GSI in have: return f"{t} already exists ({status}; indexes {', '.join(sorted(have))})"
        ddb.call("UpdateTable", {"TableName": t,
                                 "AttributeDefinitions": [{"AttributeName": a, "AttributeType": "S"} for a in ("gsi2pk", "gsi2sk")],
                                 "GlobalSecondaryIndexUpdates": [{"Create": _gsi(TASK_GSI, "gsi2pk", "gsi2sk")}]})
        for _ in range(300):
            if ddb.indexes(name).get(TASK_GSI) == "ACTIVE": return f"{t}: added index {TASK_GSI}"
            time.sleep(2)
        return f"{t}: index {TASK_GSI} still building after 10 minutes"
    ddb.call("CreateTable", {
        "TableName": t, "BillingMode": "PAY_PER_REQUEST",
        "AttributeDefinitions": [{"AttributeName": a, "AttributeType": "S"}
                                 for a in ("pk", "sk", "gsi1pk", "gsi1sk", "gsi2pk", "gsi2sk")],
        "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
        "GlobalSecondaryIndexes": [_gsi(GSI, "gsi1pk", "gsi1sk"), _gsi(TASK_GSI, "gsi2pk", "gsi2sk")]})
    for _ in range(60):
        if ddb.exists(name) == "ACTIVE": return f"created {t} (pk/sk + indexes {GSI}, {TASK_GSI})"
        time.sleep(1)
    return f"created {t}, still not ACTIVE after 60s"


def publish_run(d, card_only=False, replace=False):
    """One run folder into the table.  `replace` clears the run's partition first, for a folder that lost files."""
    rid = os.path.basename(d.rstrip("/"))
    if replace and not card_only: ddb.delete_partition(run_pk(rid))
    items = items_of_run(d, card_only)
    ddb.batch_put(items)
    if not card_only:
        # A finished run changes two other cards: its harness's tally and its task's results.
        card = items[0]
        publish_harness((card.get("harness") or {}).get("name"))
        t = card.get("task") or {}
        if card.get("kind") == "harbor" and t.get("taskset"): refresh_task(t["taskset"], t.get("name"))
    return rid, len(items)


def publish_recipe(path):
    items = items_of_recipe(path)
    ddb.batch_put(items)
    return items[0]["recipe"], len(items)


def publish_card(ev):
    """One evaluation's card into the table, from the record rather than from a folder."""
    items = eval_card(ev)
    ddb.batch_put(items)
    return len(items)


def publish_eval(eid):
    items = items_of_eval(eid)
    ddb.batch_put(items)
    return eid, len(items)


# ------------------------------------------------------------------ harnesses and tasks, as rows
def _outcome(card):
    """One run, as the one word a results grid shows."""
    if card.get("status") == "running" or not card.get("finished"): return "running"
    r = card.get("reward")
    if r is None: return "error"
    return "pass" if r == 1 else "fail"


def results_of(cards, key):
    """Fold run cards into {key(card): {runs, passes, last, last_run, last_outcome, best}}, oldest to newest."""
    out = {}
    for c in sorted(cards, key=lambda c: (c.get("started") or "", c.get("run") or "")):
        k = key(c)
        if not k: continue
        r = out.setdefault(k, {"runs": 0, "passes": 0})
        o = _outcome(c)
        r["runs"] += 1; r["passes"] += o == "pass"
        r.update(last=c.get("started"), last_run=c.get("run"), last_outcome=o,
                 last_reward=c.get("reward"), last_tests=c.get("tests"))
    return out


def harness_card(name):
    """A harness, summed up from its runs and its recipes: what the harness page and llms.txt lead with."""
    runs = harness_runs(name)
    # The index holds each recipe twice (the list row and the META row that carries the Dockerfile); keep the list row.
    recipes = [strip(i) for i in ddb.query(harness_pk(name), "RECIPE#", index=GSI) if i.get("pk") == RECIPELIST]
    latest = max(runs, key=lambda c: c.get("started") or "", default={})
    rec = next((r for r in recipes if r.get("commit") == (latest.get("harness") or {}).get("commit")), None) \
        or (recipes[-1] if recipes else {})
    h = latest.get("harness") or {}
    task_results = results_of([c for c in runs if c.get("kind") == "harbor"],
                              lambda c: f"{(c.get('task') or {}).get('taskset')}/{(c.get('task') or {}).get('name')}")
    finished = [c for c in runs if _outcome(c) in ("pass", "fail", "error")]
    profile = strip(ddb.get(harness_pk(name), "PROFILE")) or None
    return {"harness": name, "repo": h.get("repo"), "commit": h.get("commit") or rec.get("commit"),
            "api_style": h.get("api_style") or rec.get("api_style"), "summary": rec.get("summary"),
            "recipe": rec.get("recipe"), "base_image": rec.get("base_image"), "recipes": len(recipes),
            "runs": len(runs), "finished": len(finished), "passes": sum(1 for c in finished if _outcome(c) == "pass"),
            "tasks_tried": len(task_results), "tasks_passed": sum(1 for r in task_results.values() if r["passes"]),
            "tasksets": sorted({k.split("/")[0] for k in task_results}), "results": task_results,
            "first_run": min((c.get("started") for c in runs if c.get("started")), default=None),
            "last_run": latest.get("started"), "last_run_id": latest.get("run"),
            "models": sorted({c.get("model") for c in runs if c.get("model")}),
            "use_case": (profile or {}).get("use_case"), "domains": (profile or {}).get("domains")}


def publish_harness(name):
    if not name: return 0
    card = harness_card(name)
    if not card["runs"] and not card["recipes"]: return 0
    return ddb.batch_put([{**card, "pk": HARNESSLIST, "sk": harness_pk(name)},
                          fit({**card, "pk": harness_pk(name), "sk": "META"}, ())])


def publish_profile(name, profile):
    ddb.put({**profile, "harness": name, "pk": harness_pk(name), "sk": "PROFILE"})
    publish_harness(name)


def publish_recs(name, recs):
    ddb.put({**recs, "harness": name, "pk": harness_pk(name), "sk": "RECS"})


def task_items(ts_card, tasks, runnable_keys=None):
    """The rows for one taskset: its card twice, a row per task, and a RUNNABLE row per task the site may start."""
    ts = ts_card["taskset"]
    items = [{**ts_card, "pk": TASKSETLIST, "sk": taskset_pk(ts)}, {**ts_card, "pk": taskset_pk(ts), "sk": "META"}]
    for t in tasks:
        row = fit({**t, "pk": taskset_pk(ts), "sk": f"TASK#{t['task']}"}, ("instruction",))
        items.append(row)
        if t.get("runnable"): items.append({**row, "pk": RUNNABLE, "sk": task_key(ts, t["task"])})
    return items


def publish_tasks(grep=None, quiet=False):
    """The Harbor corpus into the table (lib/tasks.py builds the cards).  Task rows that already carry `results`
    keep them — the corpus knows nothing about runs, the runs index does."""
    import tasks as corpus
    n = rows = 0
    for ts_card, ts_tasks in corpus.corpus():
        if grep and not re.search(grep, ts_card["taskset"]): continue
        old = {r["sk"]: r.get("results") for r in ddb.query(taskset_pk(ts_card["taskset"]), "TASK#", attributes=["sk", "results"])}
        for t in ts_tasks:
            if old.get(f"TASK#{t['task']}"): t["results"] = old[f"TASK#{t['task']}"]
        items = task_items(ts_card, ts_tasks)
        ddb.batch_put(items); n += 1; rows += len(items)
        if not quiet: print(f"  taskset {ts_card['taskset']:40s} {len(ts_tasks):6d} tasks  {ts_card['n_runnable']} runnable")
    # A task that fell out of the runnable pool has to leave the RUNNABLE list too.
    live = {r["sk"] for r in ddb.query(RUNNABLE, "TASK#", attributes=["pk", "sk"])}
    keep = {task_key(t["taskset"], t["task"]) for t in runnable_list(fresh=True)}
    stale = live - keep
    if stale and not grep:
        t_ = ddb.table()
        for sk in sorted(stale):
            ddb.call("DeleteItem", {"TableName": t_, "Key": {"pk": {"S": RUNNABLE}, "sk": {"S": sk}}})
    return n, rows


def runnable_list(fresh=False):
    """The tasks the site may start.  `fresh` reads them from the corpus rows rather than the RUNNABLE list."""
    if not fresh: return [strip(i) for i in ddb.query(RUNNABLE, "TASK#")]
    import tasks as corpus
    keys = corpus.runnable_set()
    return [{"taskset": ts, "task": t} for ts, t in sorted(keys)]


def refresh_task(ts, name):
    """Fold every run on one task into its card's `results`, keyed by harness.  Runs publish this; the corpus
    sync keeps it."""
    if not ts or not name: return 0
    row = ddb.get(taskset_pk(ts), f"TASK#{name}")
    if not row: return 0
    runs = task_runs(ts, name)
    row["results"] = results_of(runs, lambda c: (c.get("harness") or {}).get("name"))
    row["runs"] = len(runs)
    items = [row]
    if row.get("runnable"): items.append({**row, "pk": RUNNABLE, "sk": task_key(ts, name)})
    return ddb.batch_put(items)


# ------------------------------------------------------------------ reading, in the shapes the site already serves
_ok = (None, 0.0)


def available(ttl=30):
    """Is a table configured and answering?  The answer is cached for half a minute — serve.py asks once per
    request, and a table that was down when the server booted has to be allowed to come back without a restart."""
    global _ok
    import time
    was, when = _ok
    if was is None or time.time() - when > ttl:
        try: was = ddb.exists() == "ACTIVE"
        except ddb.Error: was = False
        _ok = (was, time.time())
    return was


KEYS = ("pk", "sk", "gsi1pk", "gsi1sk", "gsi2pk", "gsi2sk")


def strip(item):
    return {k: v for k, v in (item or {}).items() if k not in KEYS}


def runs_list(limit=None):
    """What /api/runs serves: one card per run, newest first (run ids start with a timestamp)."""
    return [strip(i) for i in ddb.query(RUNLIST, "RUN#", desc=True, limit=limit)]


def harness_runs(name, limit=None):
    """Every run of one harness, oldest first, out of the index."""
    return [strip(i) for i in ddb.query(harness_pk(name), "RUN#", index=GSI, limit=limit)]


def recipes_list():
    return [strip(i) for i in ddb.query(RECIPELIST, "RECIPE#")]


def recipe(rid):
    return strip(ddb.get(recipe_pk(rid), "META"))


def run_bundle(rid):
    """What /api/run/<id> serves, assembled from the run's partition: the card, the recipe, every call, the text of
    the files the page shows, the verifier's output and the file list."""
    rows = ddb.query(run_pk(rid))
    if not rows: return None
    by_sk = {r["sk"]: r for r in rows}
    if "META" not in by_sk: return None
    files = {r["sk"][len("FILE#"):]: r for r in rows if r["sk"].startswith("FILE#")}
    calls = []
    for r in rows:
        if not r["sk"].startswith("CALL#"): continue
        c = strip(r)
        for f in ("request", "response"):
            try: c[f] = json.loads(c.get(f) or "null")
            except ValueError: pass                       # a truncated payload stays the string it is
        calls.append(c)
    tests = strip(by_sk.get("TESTS")) or None
    if tests:
        try: tests["cases"] = json.loads(tests.get("cases") or "null")
        except ValueError: tests["cases"] = None
    verifier_out = {k: (files.get(f"verifier/{k}") or {}).get("text") for k in ("stdout.log", "stderr.log", "reward.txt")}
    manifest = strip(by_sk.get("MANIFEST")) or {}
    return {"run": rid, "run_json": strip(by_sk["META"]),
            "recipe": json.loads((files.get("recipe.json") or {}).get("text") or "null"),
            "calls": calls, "calls_unparsed": by_sk["META"].get("calls_unparsed") or 0,
            **{short: (files.get(name) or {}).get("text") for name, short in BUNDLE_KEYS.items()},
            "verifier": {**verifier_out, "tests": tests} if manifest.get("has_verifier") else None,
            "files": manifest.get("files") or [], "files_omitted": manifest.get("files_omitted") or 0,
            "egress": [strip(r) for r in rows if r["sk"].startswith("EGRESS#")],
            # Where this answer came from, and which of the files in it lost bytes to the 400 KB item limit — a page
            # showing a cut log has to be able to say so, and to link the whole file.
            "source": "table", "truncated": sorted(n for n, r in files.items() if r.get("truncated"))}


def run_files(rid):
    """Just the file list — one GetItem, for a page that polls "what has this run written so far"."""
    m = strip(ddb.get(run_pk(rid), "MANIFEST"))
    if not m: return None
    return {"run": rid, "files": m.get("files") or [], "files_omitted": m.get("files_omitted") or 0, "source": "table"}


# ------------------------------------------------------------------ evaluations, read back

def run_card(rid):
    """One run's card without its calls or files — what a finished evaluation shows as its result."""
    return strip(ddb.get(run_pk(rid), "META")) or None


def evals_list(limit=None):
    """Every evaluation, newest first.  Eval ids start with a timestamp, so the sort key does the ordering."""
    return [strip(i) for i in ddb.query(EVALLIST, "EVAL#", desc=True, limit=limit)]


def eval_record(eid):
    """One evaluation's META row: the record, plus the console text and the live counters a runner publishes."""
    return strip(ddb.get(eval_pk(eid), "META")) or None


def eval_events(eid, after=0):
    """The stage events run.sh emitted, from `after` on, and the new cursor — the same contract the folder-backed
    reader has, so the page polls identically whichever side is answering."""
    rows = [strip(r) for r in ddb.query(eval_pk(eid), "EVENT#")]
    return rows[after:], len(rows)


def running_eval():
    """The evaluation the fleet is working on now, if any.  One at a time is enforced on the way in."""
    for card in evals_list(limit=25):
        if card.get("status") in ("queued", "running"): return card
    return None


# ------------------------------------------------------------------ harnesses and tasks, read back

TASK_LIST_FIELDS = ["taskset", "task", "difficulty", "category", "language", "tags", "runnable", "compose", "results",
                    "runs", "oracle", "agent_timeout"]


def harnesses_list():
    return [strip(i) for i in ddb.query(HARNESSLIST, "HARNESS#")]


def harness(name):
    return strip(ddb.get(harness_pk(name), "META")) or None


def harness_profile(name):
    return strip(ddb.get(harness_pk(name), "PROFILE")) or None


def harness_recs(name):
    return strip(ddb.get(harness_pk(name), "RECS")) or None


def tasksets_list():
    return [strip(i) for i in ddb.query(TASKSETLIST, "TASKSET#")]


def taskset(ts):
    return strip(ddb.get(taskset_pk(ts), "META")) or None


def taskset_tasks(ts, after=None, limit=200):
    """One page of a taskset's tasks, without their instructions, and the cursor for the next page (None at the end).
    The largest taskset has 33,786 tasks, so a page is the only honest unit."""
    rows = ddb.query(taskset_pk(ts), "TASK#", limit=limit + 1, attributes=["sk", *TASK_LIST_FIELDS],
                     after=f"TASK#{after}" if after else None)
    more = len(rows) > limit
    rows = rows[:limit]
    return [strip(r) for r in rows], (rows[-1]["task"] if more and rows else None)


def task(ts, name):
    return strip(ddb.get(taskset_pk(ts), f"TASK#{name}")) or None


def task_runs(ts, name):
    """Every harness's runs on one task, oldest first, out of the `task` index."""
    return [strip(i) for i in ddb.query(task_key(ts, name), "RUN#", index=TASK_GSI)]


def file_text(rid, name):
    """One stored file's text, for /raw/<run-id>/<file> when the folder is not on this machine."""
    row = ddb.get(run_pk(rid), f"FILE#{name}")
    return row.get("text") if row else None


# ------------------------------------------------------------------ CLI
def cmd_sync(a):
    what = [w for w in ("runs", "recipes", "evals", "tasks", "harnesses") if getattr(a, w)] or ["runs", "recipes", "evals", "harnesses"]
    if "tasks" in what:
        k, rows = publish_tasks(a.grep, a.quiet)
        n += k; items += rows
    n = items = 0
    if "runs" in what:
        for rid in sorted(os.listdir(RUNS) if os.path.isdir(RUNS) else []):
            d = os.path.join(RUNS, rid)
            if not os.path.isdir(d) or rid.startswith(".") or (a.grep and not re.search(a.grep, rid)): continue
            _, k = publish_run(d, replace=a.replace); n += 1; items += k
            if not a.quiet: print(f"  run     {rid}  ({k} rows)")
    if "recipes" in what:
        for f in sorted(os.listdir(RECIPES) if os.path.isdir(RECIPES) else []):
            if not RECIPE_FILE.match(f) or (a.grep and not re.search(a.grep, f)): continue
            rid, k = publish_recipe(os.path.join(RECIPES, f)); n += 1; items += k
            if not a.quiet: print(f"  recipe  {rid}  ({k} rows)")
    if "evals" in what:
        for eid in sorted(os.listdir(EVALS) if os.path.isdir(EVALS) else []):
            if not os.path.isdir(os.path.join(EVALS, eid)) or (a.grep and not re.search(a.grep, eid)): continue
            _, k = publish_eval(eid); n += 1; items += k
            if not a.quiet: print(f"  eval    {eid}  ({k} rows)")
    if "harnesses" in what:
        cards = ddb.query(RUNLIST, "RUN#", attributes=["harness", "task", "kind"])
        # Each task a run has touched gets its results re-folded — a run published before its task card existed
        # (or before the corpus was synced) would otherwise never show on the task's page.
        for ts, name in sorted({((c.get("task") or {}).get("taskset"), (c.get("task") or {}).get("name"))
                                for c in cards if c.get("kind") == "harbor"}):
            if ts and name and (not a.grep or re.search(a.grep, ts)): refresh_task(ts, name)
        names = {(c.get("harness") or {}).get("name") for c in cards}
        names |= {c.get("harness") for c in ddb.query(RECIPELIST, "RECIPE#", attributes=["harness"])}
        for name in sorted(x for x in names if x and (not a.grep or re.search(a.grep, x))):
            k = publish_harness(name); n += 1; items += k
            if not a.quiet: print(f"  harness {name}  ({k} rows)")
    print(f"{n} published, {items} rows → {ddb.target()}")


def cmd_status(a):
    status = ddb.exists()
    if not status: return print(f"{ddb.target()}: no such table (lib/store.py table creates it)")
    runs = ddb.query(RUNLIST, "RUN#", attributes=["pk", "sk", "status", "reward"])
    recipes = ddb.query(RECIPELIST, "RECIPE#", attributes=["pk", "sk"])
    evals = ddb.query(EVALLIST, "EVAL#", attributes=["pk", "sk"])
    harnesses = ddb.query(HARNESSLIST, "HARNESS#", attributes=["pk", "sk"])
    tasksets = ddb.query(TASKSETLIST, "TASKSET#", attributes=["pk", "sk", "n_tasks"])
    runnable = ddb.query(RUNNABLE, "TASK#", attributes=["pk", "sk"])
    print(f"{ddb.target()}   {status}   indexes: {', '.join(sorted(ddb.indexes()))}")
    print(f"  runs     {len(runs)}   ({sum(1 for r in runs if r.get('status') == 'running')} running, "
          f"{sum(1 for r in runs if r.get('reward'))} rewarded)")
    print(f"  recipes  {len(recipes)}")
    print(f"  evals    {len(evals)}")
    print(f"  harnesses {len(harnesses)}")
    print(f"  tasksets {len(tasksets)}   ({sum(t.get('n_tasks') or 0 for t in tasksets)} tasks, {len(runnable)} runnable)")


def main():
    ap = argparse.ArgumentParser(prog="store.py", description="everything about a run, in one DynamoDB table")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("table")
    sub.add_parser("target")
    sub.add_parser("status")
    p = sub.add_parser("publish"); p.add_argument("dir"); p.add_argument("--card", action="store_true")
    p.add_argument("--replace", action="store_true")
    p = sub.add_parser("recipe"); p.add_argument("file")
    p = sub.add_parser("eval"); p.add_argument("id")
    p = sub.add_parser("sync"); p.add_argument("--grep"); p.add_argument("--quiet", action="store_true")
    p.add_argument("--replace", action="store_true")
    for w in ("runs", "recipes", "evals", "tasks", "harnesses"): p.add_argument(f"--{w}", action="store_true")
    p = sub.add_parser("runs"); p.add_argument("--limit", type=int)
    p = sub.add_parser("run"); p.add_argument("id")
    sub.add_parser("recipes")
    p = sub.add_parser("harness"); p.add_argument("name")
    a = ap.parse_args()
    try:
        if a.cmd == "table": print(create_table())
        elif a.cmd == "target": print(f"{ddb.target()}   {ddb.exists() or 'no such table'}")
        elif a.cmd == "status": cmd_status(a)
        elif a.cmd == "publish":
            rid, k = publish_run(a.dir, a.card, a.replace); print(f"{rid}: {k} rows → {ddb.target()}")
        elif a.cmd == "recipe":
            rid, k = publish_recipe(a.file); print(f"{rid}: {k} rows → {ddb.target()}")
        elif a.cmd == "eval":
            rid, k = publish_eval(a.id); print(f"{rid}: {k} rows → {ddb.target()}")
        elif a.cmd == "sync": cmd_sync(a)
        elif a.cmd == "runs": print(json.dumps(runs_list(a.limit), indent=2))
        elif a.cmd == "run": print(json.dumps(run_bundle(a.id), indent=2))
        elif a.cmd == "recipes": print(json.dumps(recipes_list(), indent=2))
        elif a.cmd == "harness": print(json.dumps(harness_runs(a.name), indent=2))
    except ddb.Error as e:
        sys.exit(f"store.py: {e}")


if __name__ == "__main__":
    main()
