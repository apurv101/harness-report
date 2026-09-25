#!/usr/bin/env python3
"""recommend.py — which tests a harness should run next, for what it is for.

Two inputs and one output, all rows in the run store:

    HARNESS#<name>/PROFILE   what the harness is for: use case, domains, languages, capabilities.  Written by
                             `profile` — claude -p reading the clone (read-only tools), cached per commit in
                             profiles/<name>@<commit>.json.  Before any run the site has no clone, so a guess from
                             the GitHub repo's language and description stands in (`guess_profile`).
    HARNESS#<name>/META      its results so far, per task (lib/store.py harness_card)
    HARNESS#<name>/RECS      the ranking: [{taskset, task, why, score}], and whether an LLM or the rules made it

The candidates are the runnable pool only — a recommendation the site cannot start is not one.

The ranking is an LLM's (claude -p, no tools, structured output) when this machine has the claude CLI, and the
rules below when it does not or the call fails.  The rules are also what picks the FIRST task on the site before
anything has run: they need nothing but the repo's language and description, so the Lambda can answer instantly.

    lib/recommend.py profile <name> [--src work/<name>/repo] [--commit sha] [--force]
    lib/recommend.py rank <name> [--rules]           rank and publish RECS
    lib/recommend.py refresh <name>                  profile if this commit has none, then rank — the hook
                                                     hr-agentd and evals.py run after every settled run
    lib/recommend.py first <owner/repo> [--language L] [--description D]   the first task, by the rules
"""
import argparse, contextlib, json, os, re, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import ddb, store                                                       # noqa: E402

PROFILES = os.path.join(ROOT, "profiles")
TOP = 5
LANG_ALIASES = {"typescript": "javascript", "ts": "javascript", "js": "javascript", "c++": "cpp", "c": "cpp",
                "golang": "go", "py": "python", "jupyter notebook": "python", "shell": "bash"}

# What each runnable taskset exercises, for the rules.  The domain is the taskset card's own facet; these are the
# capability words a profile can match beyond it.
TASKSET_TRAITS = {
    "aider_polyglot": {"edits-files", "runs-tests"}, "swebench-verified": {"edits-files", "runs-tests", "uses-git", "long-horizon"},
    "quixbugs": {"edits-files"}, "humanevalfix": {"edits-files", "runs-tests"}, "usaco": {"edits-files", "runs-shell"},
    "spider2-dbt": {"queries-sql", "runs-shell", "edits-files"}, "bird-bench": {"queries-sql"},
    "bigcodebench_hard_complete": {"edits-files", "calls-apis"}, "algotune": {"edits-files", "runs-shell", "long-horizon"},
    "evoeval": {"edits-files"}, "crustbench": {"edits-files", "runs-shell", "long-horizon"}, "dabstep": {"reads-docs", "runs-shell"},
}


def log(msg): print(f"recommend: {msg}", file=sys.stderr, flush=True)


def lang(x): x = (x or "").lower().strip(); return LANG_ALIASES.get(x, x)


# ------------------------------------------------------------------ profile
def guess_profile(language=None, description=None):
    """What the repo is for, from nothing but its GitHub language and description.  Coarse on purpose: it only
    has to pick a sensible first task, and the real profile replaces it after the first run."""
    d = (description or "").lower()
    domains = []
    for dom, pat in (("data-sql", r"\bsql\b|database|dbt|analytics|data ?(science|engineer)"),
                     ("devops-sre", r"devops|terminal|shell|kubernetes|infra|sre"),
                     ("web-research", r"browser|web ?(agent|research)|\bsearch|deep research"),
                     ("ml-research", r"\bml\b|machine learning|research agent|training"),
                     ("swe", r"cod(e|ing)|software|program|developer|ide\b|pair.?program|repo|pull request|bug")):
        if re.search(pat, d): domains.append(dom)
    if not domains: domains = ["swe"]
    return {"use_case": description or None, "domains": domains, "languages": [lang(language)] if language else [],
            "capabilities": [], "not_for": [], "source": "github-metadata"}


def profile(name, src=None, commit=None, force=False):
    """claude -p reads the clone and says what the harness is for.  Cached per commit; published either way."""
    src = src or os.path.join(ROOT, "work", name, "repo")
    if not os.path.isdir(src): raise SystemExit(f"no clone at {src}")
    commit = commit or subprocess.run(["git", "-C", src, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    os.makedirs(PROFILES, exist_ok=True)
    cache = os.path.join(PROFILES, f"{name}@{commit}.json")
    if os.path.exists(cache) and not force:
        prof = json.load(open(cache))
    else:
        prompt = open(os.path.join(HERE, "profile-prompt.md")).read()
        schema = open(os.path.join(HERE, "profile-schema.json")).read()
        model = os.environ.get("PROFILE_MODEL") or os.environ.get("ANALYZER_MODEL")
        t0 = time.time()
        # Read-only by construction, not by request: the analyzer's --allowedTools alone did not stop Bash under a
        # global auto permission mode, so --tools removes every other tool from the session.
        p = subprocess.run(["claude", "-p", prompt, "--output-format", "json", "--json-schema", schema,
                            "--tools", "Read,Glob,Grep", "--allowedTools", "Read,Glob,Grep",
                            "--max-turns", "25", "--strict-mcp-config", *(["--model", model] if model else [])],
                           cwd=src, capture_output=True, text=True, timeout=900)
        try: out = json.loads(p.stdout)
        except ValueError: raise SystemExit(f"profile: claude -p gave no JSON (rc={p.returncode}): {p.stderr[-400:]}")
        so = out.get("structured_output")
        if not so: raise SystemExit(f"profile: no structured output ({out.get('subtype')}): {str(out.get('result'))[:300]}")
        prof = {**so, "source": "claude -p", "commit": commit, "seconds": round(time.time() - t0),
                "cost_usd": out.get("total_cost_usd"), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        prof["languages"] = sorted({lang(x) for x in prof.get("languages") or [] if x})
        with tempfile.NamedTemporaryFile(mode="w", dir=PROFILES, delete=False) as f:
            json.dump(prof, f, indent=2)
        os.replace(f.name, cache)
    store.publish_profile(name, prof)
    return prof


# ------------------------------------------------------------------ candidates
def candidates():
    by_ts = {t["taskset"]: t for t in store.tasksets_list()}
    out = []
    for t in store.runnable_list():
        ts = by_ts.get(t["taskset"]) or {}
        out.append({"taskset": t["taskset"], "task": t["task"], "domain": ts.get("domain"),
                    "language": lang(t.get("language")) or next((lang(x) for x in t.get("tags") or [] if lang(x) in
                                                                 ("python", "go", "rust", "java", "javascript", "cpp", "sql")), None),
                    "difficulty": t.get("difficulty"), "category": t.get("category"),
                    "traits": sorted(TASKSET_TRAITS.get(t["taskset"], ())),
                    "instruction": re.sub(r"\s+", " ", t.get("instruction") or "")[:400],
                    "results": t.get("results") or {}})
    return out


# ------------------------------------------------------------------ rules
def rank_rules(prof, results, pool, top=TOP):
    """Domain first, then language, then a new taskset over one already tried, and never a task it already has a reward on.
    One pick per taskset before a second from any, so five recommendations cover five kinds of work."""
    doms = prof.get("domains") or []
    langs = set(prof.get("languages") or [])
    caps = set(prof.get("capabilities") or [])
    tried_ts = {k.split("/")[0] for k in results}
    scored = []
    for c in pool:
        key = f"{c['taskset']}/{c['task']}"
        r = results.get(key) or {}
        if r.get("scored"): continue
        s, why = 0.0, []
        if c["domain"] in doms:
            s += 4 - doms.index(c["domain"]); why.append(f"{c['domain']} is what it is built for")
        if c["language"] and c["language"] in langs:
            s += 2; why.append(f"written in {c['language']}")
        overlap = caps & set(c["traits"])
        if overlap: s += 0.5 * len(overlap)
        if c["taskset"] not in tried_ts:
            s += 1.5; why.append("a taskset it has not tried")
        if r.get("runs"): s -= 2; why.append("ran before without a reward — worth a retry after a fix")
        if c["domain"] not in doms and not (c["language"] and c["language"] in langs): s -= 1
        scored.append((s, c, why))
    scored.sort(key=lambda x: (-x[0], x[1]["taskset"], x[1]["task"]))
    out, seen = [], set()
    for rnd in (0, 1):
        for s, c, why in scored:
            if len(out) >= top: break
            if (rnd == 0 and c["taskset"] in seen) or any(o["task"] == c["task"] and o["taskset"] == c["taskset"] for o in out): continue
            seen.add(c["taskset"])
            out.append({"taskset": c["taskset"], "task": c["task"], "score": round(s, 2),
                        "why": "; ".join(why) or "broadens coverage", "domain": c["domain"], "language": c["language"]})
    return out


# ------------------------------------------------------------------ LLM
RANK_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["recs"], "properties": {"recs": {
    "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["taskset", "task", "why"],
                               "properties": {"taskset": {"type": "string"}, "task": {"type": "string"},
                                              "why": {"type": "string", "description": "one short sentence, to the harness author"}}}}}}


def rank_llm(name, prof, results, pool, top=TOP):
    card = store.harness(name) or {}
    brief = {"harness": name, "profile": {k: prof.get(k) for k in ("use_case", "domains", "languages", "capabilities", "not_for")},
             "how_it_runs": (card.get("summary") or "")[:800],
             "results_so_far": {k: {"runs": v.get("runs"), "last": v.get("last_outcome"), "last_reward": v.get("last_reward"),
                                    "best_reward": v.get("best_reward"),
                                    "tests": (v.get("last_tests") or {}).get("summary")} for k, v in results.items()},
             "candidates": [{k: c[k] for k in ("taskset", "task", "domain", "language", "difficulty", "traits", "instruction")}
                            | {"harnesses_tried": len(c["results"])}
                            for c in pool]}
    prompt = (f"You pick the next {top} benchmark tasks for the author of an AI agent harness to run, from the candidates "
              "below (use their exact taskset and task strings). Choose what tells the author the most about how the "
              "harness does at what it is FOR: cover its main domains and languages first, prefer tasksets it has not "
              "tried, step up in difficulty where its tests already pass, and never pick a task it already has a reward on. "
              "A reward is whatever that task's verifier wrote and means different things per taskset (1/0 for all "
              "tests passing, a speedup with a floor of 1 for AlgoTune, a fraction for a judge), so read the test "
              "summary alongside it, not the number alone. Spread across tasksets. For each, one sentence of why, "
              "addressed to the author.\n\n" + json.dumps(brief))
    model = os.environ.get("RECOMMEND_MODEL") or "haiku"
    p = subprocess.run(["claude", "-p", prompt, "--output-format", "json", "--json-schema", json.dumps(RANK_SCHEMA),
                        "--tools", "", "--max-turns", "3", "--strict-mcp-config", "--model", model],
                       capture_output=True, text=True, timeout=300, cwd=os.path.join(ROOT, "work") if os.path.isdir(os.path.join(ROOT, "work")) else ROOT)
    out = json.loads(p.stdout)
    so = out.get("structured_output") or {}
    valid = {(c["taskset"], c["task"]): c for c in pool}
    recs = []
    for r in so.get("recs") or []:
        c = valid.get((r.get("taskset"), r.get("task")))
        if not c or (results.get(f"{c['taskset']}/{c['task']}") or {}).get("scored"): continue
        if any(x["task"] == c["task"] and x["taskset"] == c["taskset"] for x in recs): continue
        recs.append({"taskset": c["taskset"], "task": c["task"], "why": r.get("why"), "score": None,
                     "domain": c["domain"], "language": c["language"]})
    if not recs: raise ValueError(f"no usable picks in {str(so)[:300]}")
    return recs[:top], {"model": model, "cost_usd": out.get("total_cost_usd")}


def rank(name, rules_only=False):
    prof = store.harness_profile(name)
    if not prof: prof = guess_profile()
    card = store.harness(name) or {}
    results = card.get("results") or {}
    pool = candidates()
    if not pool: raise SystemExit("no runnable tasks in the table — ./run.sh ddb sync --tasks")
    meta, source = {}, "rules"
    recs = None
    if not rules_only and os.environ.get("HR_RECOMMEND", "llm") != "rules":
        try:
            recs, meta = rank_llm(name, prof, results, pool); source = "llm"
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            log(f"{name}: LLM ranking failed, using the rules: {e}")
    if not recs: recs = rank_rules(prof, results, pool)
    row = {"recs": recs, "source": source, **meta, "profile_source": prof.get("source"),
           "based_on_run": card.get("last_run_id"), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    store.publish_recs(name, row)
    return row


@contextlib.contextmanager
def refresh_lock(name):
    if os.environ.get("HR_EVALS") != "local-queue":
        yield
        return
    import fcntl
    os.makedirs(PROFILES, exist_ok=True)
    with open(os.path.join(PROFILES, f".{name}.lock"), "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def refresh(name, src=None):
    """After a run: profile the clone if this commit has no profile yet, then re-rank.  Never raises — a run has
    already finished and been published; this only adds advice beside it."""
    try:
        with refresh_lock(name):
            card = store.harness(name) or {}
            have = store.harness_profile(name) or {}
            # Concurrent jobs can finish with different commits. Never label an older clone as the latest one.
            clone_commit = subprocess.run(["git", "-C", src, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip() if src else card.get("commit")
            if clone_commit == card.get("commit") and (have.get("commit") != clone_commit or have.get("source") != "claude -p"):
                try: profile(name, src=src, commit=clone_commit)
                except (SystemExit, OSError, subprocess.SubprocessError, ValueError) as e: log(f"{name}: no profile: {e}")
            return rank(name)
    except (ddb.Error, SystemExit, OSError, ValueError) as e:
        log(f"{name}: no recommendations: {e}")
        return None


def spawn_refresh(name, src=None):
    """refresh() in a detached process, so the caller (a request thread, the runner's loop) is not held for the
    minute a profile takes."""
    try:
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "refresh", name, *(["--src", src] if src else [])], cwd=ROOT,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=open(os.path.join(ROOT, "work", f"recommend-{name}.log"), "a")
                         if os.path.isdir(os.path.join(ROOT, "work")) else subprocess.DEVNULL, start_new_session=True)
    except OSError as e: log(f"could not start refresh for {name}: {e}")


def first(repo, language=None, description=None):
    """The first task for a repo on the site: its recommendations if it has any, else the rules on a guess."""
    name = store.harness_name(repo)
    recs = store.harness_recs(name)
    pool = candidates()
    live = {(c["taskset"], c["task"]) for c in pool}
    if recs:
        for r in recs.get("recs") or []:
            if (r["taskset"], r["task"]) in live: return {**r, "source": recs.get("source"), "harness": name, "recs": recs.get("recs")}
    prof = store.harness_profile(name) or guess_profile(language, description)
    picks = rank_rules(prof, (store.harness(name) or {}).get("results") or {}, pool)
    if not picks: return None
    return {**picks[0], "source": "rules", "harness": name, "recs": picks, "profile": prof}


def main():
    ap = argparse.ArgumentParser(prog="recommend.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("profile"); p.add_argument("name"); p.add_argument("--src"); p.add_argument("--commit"); p.add_argument("--force", action="store_true")
    p = sub.add_parser("rank"); p.add_argument("name"); p.add_argument("--rules", action="store_true")
    p = sub.add_parser("refresh"); p.add_argument("name"); p.add_argument("--src")
    p = sub.add_parser("first"); p.add_argument("repo"); p.add_argument("--language"); p.add_argument("--description")
    a = ap.parse_args()
    if a.cmd == "profile": print(json.dumps(profile(a.name, a.src, a.commit, a.force), indent=2))
    elif a.cmd == "rank": print(json.dumps(rank(a.name, a.rules), indent=2))
    elif a.cmd == "refresh": print(json.dumps(refresh(a.name, a.src), indent=2))
    elif a.cmd == "first": print(json.dumps(first(a.repo, a.language, a.description), indent=2))


if __name__ == "__main__":
    main()
