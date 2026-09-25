#!/usr/bin/env python3
"""tasks.py — the Harbor corpus as cards: one per taskset, one per task, ready for lib/store.py to publish.

The corpus lives on the runner's disk ($HARBOR_TASKS, ~93k task folders listed by its TASK-INDEX.json); the site
has no disk, so everything a page says about a task comes from these cards.  Three sources are joined:

    TASK-INDEX.json + each task.toml / instruction.md   what the task is
    catalog/index.jsonl (+ raw/harbor-coverage.jsonl)    who made the benchmark, its domain, how it grades
    catalog/runnable.json + catalog/oracle.jsonl         whether the site may start it

A task is `runnable` only when it is a candidate in runnable.json AND its newest oracle line says reward 1 —
the reference solution passes the task's own tests on the runner's platform (`./run.sh oracle`).

    lib/tasks.py stats                      how many tasksets / tasks / runnable, without writing anything
    lib/tasks.py card <taskset> <task>      one task card, as JSON
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import task as task_toml                                                # noqa: E402

CATALOG = os.path.join(ROOT, "catalog")
HARBOR_TASKS = os.environ.get("HARBOR_TASKS", os.path.expanduser("~/Desktop/harbor-tasks"))
INSTRUCTION_INLINE = 16_000     # characters of instruction.md kept on the card; the rest is on the runner's disk


def ts_name(path):
    """The taskset's name exactly as run.sh writes it into run.json (lib/harbor.sh select_tasks), so a run card
    and a task card agree on it without a lookup."""
    return re.sub(r"[^a-z0-9_.\-\n]", "-", os.path.basename(path.rstrip("/")).lower())


def _key(s):
    k = re.sub(r"[^a-z0-9]", "", (s or "").lower())
    return re.sub(r"bench(mark)?$", "", k) or k


def _jsonl(path):
    try:
        with open(path) as f: return [json.loads(l) for l in f if l.strip()]
    except OSError: return []


def catalog_rows():
    """taskset dir (e.g. 'datasets/aider_polyglot') → the catalog row describing that benchmark, where one exists."""
    by_key = {_key(r["id"]): r for r in _jsonl(os.path.join(CATALOG, "index.jsonl"))}
    for r in list(by_key.values()):
        h = r.get("harbor") or {}
        if h.get("harbor_dataset"): by_key.setdefault(_key(h["harbor_dataset"].split("/")[-1].split("@")[0]), r)
    out = {}
    for c in _jsonl(os.path.join(CATALOG, "raw", "harbor-coverage.jsonl")):
        row = by_key.get(_key(c["id"])) or next((by_key[_key(a)] for a in c.get("aliases") or [] if _key(a) in by_key), None)
        for p in c.get("local_path") or []:
            if row: out.setdefault(p, row)
    return out


def runnable_set():
    """{(taskset, task)} that the site may start: a candidate whose newest oracle result is a pass."""
    try: cands = {(t["taskset"], t["task"]) for t in json.load(open(os.path.join(CATALOG, "runnable.json")))["tasks"]}
    except (OSError, ValueError, KeyError): cands = set()
    return {k for k, v in oracle_results().items() if k in cands and v.get("reward") == 1}


def oracle_results():
    newest = {}
    for r in _jsonl(os.path.join(CATALOG, "oracle.jsonl")): newest[(r["taskset"], r["task"])] = r
    return newest


def _read(path, limit=None):
    try:
        with open(path, encoding="utf-8", errors="replace") as f: s = f.read()
    except OSError: return None, False
    if limit and len(s) > limit: return s[:limit], True
    return s, False


CATALOG_FIELDS = ("name", "owner_org", "owner_type", "domain", "domain_raw", "task_kind", "grading", "environment",
                  "license", "url_repo", "url_paper", "url_data", "cited_by")


def task_card(ts_dir, name, ts, runnable=frozenset(), oracle=None):
    d = os.path.join(ts_dir, name)
    m = task_toml.meta(d)
    instr, cut = _read(os.path.join(d, "instruction.md"), INSTRUCTION_INLINE)
    o = (oracle or {}).get((ts, name))
    return {"taskset": ts, "task": name, **m,
            "instruction": instr, "instruction_truncated": cut,
            "has_solution": os.path.exists(os.path.join(d, "solution", "solve.sh")),
            "runnable": (ts, name) in runnable,
            "oracle": {k: o.get(k) for k in ("reward", "seconds", "platform", "at")} if o else None}


def corpus():
    """Yield (taskset_card, [task_card, ...]) for every taskset in TASK-INDEX.json, in index order."""
    index = json.load(open(os.path.join(HARBOR_TASKS, "TASK-INDEX.json")))
    cat, runnable, oracle = catalog_rows(), runnable_set(), oracle_results()
    seen = set()
    for rel, paths in index.items():
        ts_dir = os.path.join(HARBOR_TASKS, rel); ts = ts_name(rel)
        # Two tasksets share a folder name (datasets/gdb and hub-datasets/gdb).  run.sh resolves a bare name to
        # datasets/ first, so that one keeps the name and the hub copy is filed as <name>-hub.
        if ts in seen: ts = f"{ts}-hub"
        seen.add(ts)
        tasks = []
        for p in sorted(paths):
            name = os.path.basename(p)
            if not os.path.exists(os.path.join(HARBOR_TASKS, p, "task.toml")): continue
            try: tasks.append(task_card(ts_dir, name, ts, runnable, oracle))
            except Exception as e:                # one malformed task.toml must not drop a taskset
                tasks.append({"taskset": ts, "task": name, "error": f"{type(e).__name__}: {e}", "runnable": False})
        row = cat.get(rel) or {}
        langs = sorted({t.get("language") for t in tasks if t.get("language")})
        diffs = {}
        for t in tasks: diffs[t.get("difficulty") or "?"] = diffs.get(t.get("difficulty") or "?", 0) + 1
        card = {"taskset": ts, "path": rel, "n_tasks": len(tasks),
                "n_single_container": sum(1 for t in tasks if not t.get("compose")),
                "n_runnable": sum(1 for t in tasks if t.get("runnable")),
                "languages": langs[:30], "difficulties": diffs,
                "categories": sorted({t.get("category") for t in tasks if t.get("category")})[:30],
                "catalog_id": row.get("id"), **{f: row.get(f) for f in CATALOG_FIELDS},
                "sample_instruction": (tasks[0].get("instruction") or "")[:1500] if tasks else None}
        card["domain"] = DOMAIN_OVERRIDES.get(ts) or card["domain"] or _guess_domain(card)
        yield card, tasks


# Tasksets the catalog does not describe, or files wrongly by keyword ("swtbench" is not multimodal).  Checked by hand
# against each taskset's instructions; everything not listed here takes the catalog's facet or the regex guess.
DOMAIN_OVERRIDES = {
    "bird-bench": "data-sql", "spider2-dbt": "data-sql", "ade-bench": "data-sql", "humanevalfix": "swe",
    "quixbugs": "swe", "swegym": "swe", "swegym-lite": "swe", "swesmith": "swe", "gso": "swe", "featbench": "swe",
    "swtbench-verified": "swe", "ml_dev_bench": "ml-research", "rexbench": "ml-research", "qcircuitbench": "science-math",
    "pixiu": "finance", "deepsynth": "web-research", "refav": "engineering-industrial", "gdb": "office-docs",
    "gdb-hub": "office-docs", "theagentcompany": "enterprise-ops",
}


def _guess_domain(card):
    """The catalog's domain facet, for a taskset the catalog does not describe: the same regex buckets, run over
    the taskset's own name and categories."""
    try:
        sys.path.insert(0, CATALOG)
        import build
        return build.domain(" ".join([card["taskset"], *card["categories"]])) or None
    except Exception:
        return None


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "card":
        rel = next(k for k in json.load(open(os.path.join(HARBOR_TASKS, "TASK-INDEX.json"))) if ts_name(k) == sys.argv[2])
        print(json.dumps(task_card(os.path.join(HARBOR_TASKS, rel), sys.argv[3], sys.argv[2], runnable_set(), oracle_results()), indent=2))
    else:
        n = t = r = 0
        for card, tasks in corpus():
            n += 1; t += len(tasks); r += card["n_runnable"]
            print(f"{card['taskset']:40s} {len(tasks):6d} tasks  {card['n_runnable']:3d} runnable  domain={card['domain']}  catalog={card['catalog_id']}")
        print(f"{n} tasksets, {t} tasks, {r} runnable")
