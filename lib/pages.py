#!/usr/bin/env python3
"""pages.py — every public page of the site as data, as Markdown, and as the HTML shell a crawler reads.

The browser renders harnesses, tasks and runs from the JSON below; an LLM or a coding agent reads the same thing
as Markdown by adding `.md` to any page URL (or `.json` for the object itself).  One function per entity builds
the object, and the Markdown and the page <head> are rendered from that object — so the three can never say
different things.

    /harnesses                 /harnesses.md             /harnesses.json
    /harnesses/<name>          /harnesses/<name>.md      /harnesses/<name>.json
    /tasks                     /tasks.md                 /tasks.json            (tasksets)
    /tasks/<taskset>           /tasks/<taskset>.md       /tasks/<taskset>.json  (?after=<task> pages it)
    /tasks/<taskset>/<task>    …/<task>.md               …/<task>.json
    /runs/<run-id>             /runs/<run-id>.md         /runs/<run-id>.json
    /llms.txt  /llms-full.txt  /sitemap.xml  /sitemaps/<name>.xml

Everything is read from the run store (lib/store.py).  Named `pages`, not `site`: a module called `site` would
shadow the one Python imports at startup.
"""
import html, json, os, re, sys
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import store                                                           # noqa: E402

BASE = os.environ.get("HR_PUBLIC_URL") or "https://harnessreport.com"
RUN_FIELDS = ("run", "started", "finished", "status", "kind", "harness", "task", "model", "reward", "tests",
              "calls", "seconds", "input_tokens", "output_tokens", "errors", "last_action")


def url(*parts, ext=""):
    return BASE + "/" + "/".join(quote(str(p), safe="") for p in parts) + ext


def run_row(c):
    """A run card cut to what a list needs — the full card is one click (or one .json) away."""
    out = {k: c.get(k) for k in RUN_FIELDS if k in c}
    out["harness"] = (c.get("harness") or {}).get("name")
    t = c.get("task") or {}
    out["task"] = {"taskset": t.get("taskset"), "name": t.get("name")} if t.get("name") else None
    out["outcome"] = store._outcome(c)
    return out


# ------------------------------------------------------------------ the objects
def harnesses():
    rows = sorted(store.harnesses_list(), key=lambda h: (-(h.get("passes") or 0), h.get("harness") or ""))
    return {"harnesses": [{k: v for k, v in h.items() if k not in ("results", "recipe")} for h in rows]}


def harness(name):
    card = store.harness(name)
    if not card: return None
    runs = [run_row(c) for c in store.harness_runs(name)]
    runs.reverse()
    return {"harness": card, "profile": store.harness_profile(name), "recommendations": store.harness_recs(name),
            "runs": runs}


def tasksets(domain=None):
    rows = store.tasksets_list()
    if domain: rows = [r for r in rows if r.get("domain") == domain]
    rows.sort(key=lambda r: (-(r.get("n_runnable") or 0), r.get("taskset")))
    return {"tasksets": [{k: v for k, v in r.items() if k != "sample_instruction"} for r in rows],
            "domains": sorted({r.get("domain") for r in store.tasksets_list() if r.get("domain")})}


def taskset(ts, after=None, runnable_only=False):
    card = store.taskset(ts)
    if not card: return None
    if runnable_only:
        tasks = [t for t in store.runnable_list() if t.get("taskset") == ts]
        tasks = [{k: t.get(k) for k in store.TASK_LIST_FIELDS} for t in tasks]
        nxt = None
    else:
        tasks, nxt = store.taskset_tasks(ts, after)
    return {"taskset": card, "tasks": tasks, "next": nxt}


def task(ts, name):
    card = store.task(ts, name)
    if not card: return None
    runs = [run_row(c) for c in store.task_runs(ts, name)]
    runs.reverse()
    return {"task": card, "runs": runs}


def run(rid):
    card = store.run_card(rid)
    if not card: return None
    return {"run": card}


def runs(limit=200):
    cards = sorted(store.runs_list(), key=lambda c: c.get("started") or "", reverse=True)[:limit]
    return {"runs": [run_row(c) for c in cards]}


def md_runs(o):
    rows = [(_link(x["run"], "runs", x["run"]), _link(x["harness"], "harnesses", x["harness"]) if x.get("harness") else "",
             f"{x['task']['taskset']}/{x['task']['name']}" if x.get("task") else "prompt", x["outcome"], _tests(x.get("tests")),
             (x.get("started") or "")[:16]) for x in o["runs"]]
    return "# Runs\n\nThe newest runs, every harness.\n\n" + _table(["run", "harness", "task", "outcome", "tests", "started"], rows) + FOOTER


def runnable():
    return {"tasks": [{k: t.get(k) for k in (*store.TASK_LIST_FIELDS, "instruction")} for t in store.runnable_list()]}


# ------------------------------------------------------------------ Markdown
def _cell(v):
    return str("" if v is None else v).replace("|", "\\|").replace("\n", " ")


def _table(head, rows):
    if not rows: return "_none yet_\n"
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def _tests(t):
    return f"{t.get('passed')}/{t.get('total')}" if isinstance(t, dict) and t.get("total") else ""


def _link(label, *parts):
    return f"[{label}]({url(*parts, ext='.md')})"


FOOTER = ("\n---\nHarness Report runs agent harnesses from their GitHub repos on Harbor tasks and records every "
          f"model call. Every page is also `.md` and `.json`; index: {BASE}/llms.txt · MCP: {BASE}/mcp\n")


def md_harnesses(o):
    rows = [(_link(h["harness"], "harnesses", h["harness"]), h.get("use_case") or (h.get("summary") or "")[:90],
             h.get("runs"), h.get("passes"), f"{h.get('tasks_passed')}/{h.get('tasks_tried')}", (h.get("last_run") or "")[:10])
            for h in o["harnesses"]]
    return ("# Harnesses\n\nEvery agent harness that has been run here, most passes first.\n\n"
            + _table(["harness", "what it is", "runs", "passes", "tasks passed/tried", "last run"], rows) + FOOTER)


def md_harness(o):
    h, p, r = o["harness"], o.get("profile") or {}, o.get("recommendations") or {}
    lines = [f"# {h['harness']}", ""]
    if p.get("use_case"): lines += [f"> {p['use_case']}", ""]
    lines += [f"- repo: {h.get('repo')}", f"- commit: {h.get('commit')}", f"- api style: {h.get('api_style')}",
              f"- runs: {h.get('runs')} ({h.get('passes')} passed)", f"- tasks passed/tried: {h.get('tasks_passed')}/{h.get('tasks_tried')}",
              f"- models: {', '.join(h.get('models') or [])}"]
    if p:
        lines += [f"- domains: {', '.join(p.get('domains') or [])}", f"- languages: {', '.join(p.get('languages') or [])}",
                  f"- capabilities: {', '.join(p.get('capabilities') or [])}"]
    if h.get("summary"): lines += ["", "## How it runs here", "", h["summary"]]
    res = h.get("results") or {}
    lines += ["", "## Results by task", "", _table(["task", "runs", "passes", "last"], [
        (_link(k, "tasks", *k.split("/", 1)), v.get("runs"), v.get("passes"), v.get("last_outcome")) for k, v in sorted(res.items())])]
    if r.get("recs"):
        lines += ["## Tests to run next", "", f"_ranked by {r.get('source')}_", "",
                  _table(["task", "why"], [(_link(f"{x['taskset']}/{x['task']}", "tasks", x["taskset"], x["task"]), x.get("why"))
                                           for x in r["recs"]])]
    lines += ["## Runs", "", _table(["run", "task", "outcome", "tests", "calls", "seconds"], [
        (_link(x["run"], "runs", x["run"]), f"{(x.get('task') or {}).get('taskset')}/{(x.get('task') or {}).get('name')}" if x.get("task") else "prompt",
         x["outcome"], _tests(x.get("tests")), x.get("calls"), x.get("seconds")) for x in o["runs"]])]
    return "\n".join(lines) + FOOTER


def md_tasksets(o):
    rows = [(_link(t["taskset"], "tasks", t["taskset"]), t.get("domain"), t.get("n_tasks"), t.get("n_runnable"),
             t.get("owner_org") or "", t.get("grading") or "") for t in o["tasksets"]]
    return ("# Tasksets\n\nHarbor tasksets indexed here. `runnable` tasks have passed their own reference solution on "
            "the runner and can be started from the site.\n\n"
            + _table(["taskset", "domain", "tasks", "runnable", "owner", "grading"], rows) + FOOTER)


def md_taskset(o):
    t = o["taskset"]
    lines = [f"# {t['taskset']}", ""]
    for k in ("domain", "n_tasks", "n_runnable", "owner_org", "grading", "task_kind", "url_repo", "url_paper"):
        if t.get(k) is not None: lines.append(f"- {k}: {t[k]}")
    if t.get("languages"): lines.append(f"- languages: {', '.join(t['languages'])}")
    lines += ["", "## Tasks", "", _table(["task", "difficulty", "language", "runnable", "harnesses tried"], [
        (_link(x["task"], "tasks", t["taskset"], x["task"]), x.get("difficulty"), x.get("language"), "yes" if x.get("runnable") else "",
         len(x.get("results") or {})) for x in o["tasks"]])]
    if o.get("next"): lines.append(f"More: {url('tasks', t['taskset'], ext='.md')}?after={quote(o['next'])}")
    return "\n".join(lines) + FOOTER


def md_task(o):
    t = o["task"]
    lines = [f"# {t['taskset']} / {t['task']}", "",
             f"- taskset: {_link(t['taskset'], 'tasks', t['taskset'])}",
             f"- difficulty: {t.get('difficulty')}", f"- category: {t.get('category')}", f"- language: {t.get('language')}",
             f"- runnable from the site: {'yes' if t.get('runnable') else 'no'}",
             f"- agent timeout: {t.get('agent_timeout')}s"]
    if t.get("oracle"): lines.append(f"- reference solution: reward {t['oracle'].get('reward')} on {t['oracle'].get('platform')}")
    res = t.get("results") or {}
    lines += ["", "## Results by harness", "", _table(["harness", "runs", "passes", "last"], [
        (_link(k, "harnesses", k), v.get("runs"), v.get("passes"), v.get("last_outcome")) for k, v in sorted(res.items())])]
    lines += ["## Instruction", "", "```", (t.get("instruction") or "").strip(), "```"]
    if t.get("instruction_truncated"): lines.append("_instruction cut at 16k characters_")
    return "\n".join(lines) + FOOTER


def md_run(o):
    c = o["run"]; h = (c.get("harness") or {}); t = c.get("task") or {}
    lines = [f"# Run {c['run']}", "",
             f"- harness: {_link(h.get('name'), 'harnesses', h.get('name'))} @ {(h.get('commit') or '')[:12]}",
             f"- task: {_link(t.get('taskset') + '/' + t.get('name'), 'tasks', t['taskset'], t['name']) if t.get('name') else 'ad-hoc prompt'}",
             f"- model: {c.get('model')}", f"- outcome: {store._outcome(c)} (reward {c.get('reward')})",
             f"- tests: {_tests(c.get('tests'))}", f"- model calls: {c.get('calls')}  tokens in/out: {c.get('input_tokens')}/{c.get('output_tokens')}",
             f"- agent seconds: {c.get('seconds')}", f"- started: {c.get('started')}",
             f"- full bundle (calls, logs, files): {BASE}/api/run/{quote(c['run'])}"]
    failed = (c.get("tests") or {}).get("failed_names") or []
    if failed: lines += ["", "## Failed tests", "", *[f"- {n}" for n in failed[:50]]]
    if c.get("last_action"): lines += ["", f"Last agent action: `{c['last_action']}`"]
    return "\n".join(lines) + FOOTER


# ------------------------------------------------------------------ routing: a page path to (object, markdown, title, description)
def resolve(parts, q=None):
    """parts is the path split on '/', with any .md/.json already stripped.  Returns (obj, md, title, desc) or None."""
    q = q or {}
    one = lambda k: (q.get(k) or [None])[0]
    if parts == ["harnesses"]:
        o = harnesses(); return o, md_harnesses(o), "Harnesses", f"{len(o['harnesses'])} agent harnesses run on real tasks, with every model call recorded."
    if len(parts) == 2 and parts[0] == "harnesses":
        o = harness(parts[1])
        if not o: return None
        h = o["harness"]
        return (o, md_harness(o), f"{h['harness']} — harness",
                f"{h['harness']}: {h.get('passes')} of {h.get('finished')} runs passed across {h.get('tasks_tried')} tasks. "
                + ((o.get("profile") or {}).get("use_case") or ""))
    if parts == ["tasks"]:
        o = tasksets(one("domain")); n = sum(t.get("n_tasks") or 0 for t in o["tasksets"])
        return o, md_tasksets(o), "Tasks", f"{len(o['tasksets'])} Harbor tasksets, {n:,} tasks, searchable by domain."
    if len(parts) == 2 and parts[0] == "tasks":
        o = taskset(parts[1], one("after"), one("runnable") in ("1", "true"))
        if not o: return None
        t = o["taskset"]
        return o, md_taskset(o), f"{t['taskset']} — taskset", f"{t['taskset']}: {t.get('n_tasks')} tasks ({t.get('domain')}), {t.get('n_runnable')} runnable here."
    if len(parts) == 3 and parts[0] == "tasks":
        o = task(parts[1], parts[2])
        if not o: return None
        t = o["task"]
        return (o, md_task(o), f"{t['task']} — {t['taskset']}",
                re.sub(r"\s+", " ", (t.get("instruction") or ""))[:180])
    if parts == ["runs"]:
        o = runs(); return o, md_runs(o), "Runs", f"The newest {len(o['runs'])} runs of agent harnesses on real tasks."
    if len(parts) == 2 and parts[0] == "runs":
        o = run(parts[1])
        if not o: return None
        c = o["run"]
        return (o, md_run(o), f"Run {c['run']}",
                f"{(c.get('harness') or {}).get('name')} on {(c.get('task') or {}).get('name') or 'a prompt'}: {store._outcome(c)}.")
    return None


PAGE_ROOTS = ("harnesses", "tasks", "runs")


def head(html_page, path, title, desc, md_path):
    """index.html with this page's title, description, canonical and a link to its Markdown twin.  The body
    keeps the empty #root the app renders into, plus a <noscript> copy of the Markdown for readers without JS."""
    t, d = html.escape(f"{title} · Harness Report"), html.escape((desc or "").strip()[:300])
    canon = BASE + path
    s = re.sub(r"<title>.*?</title>", f"<title>{t}</title>", html_page, count=1, flags=re.S)
    s = re.sub(r'<meta name="description" content="[^"]*">', f'<meta name="description" content="{d}">', s, count=1)
    s = re.sub(r'<meta name="robots" content="[^"]*">', '<meta name="robots" content="index, follow">', s, count=1)
    s = re.sub(r'<link rel="canonical" href="[^"]*">', f'<link rel="canonical" href="{html.escape(canon)}">', s, count=1)
    s = re.sub(r'<meta property="og:title" content="[^"]*">', f'<meta property="og:title" content="{t}">', s, count=1)
    s = re.sub(r'<meta property="og:description" content="[^"]*">', f'<meta property="og:description" content="{d}">', s, count=1)
    s = re.sub(r'<meta property="og:url" content="[^"]*">', f'<meta property="og:url" content="{html.escape(canon)}">', s, count=1)
    alt = (f'<link rel="alternate" type="text/markdown" href="{html.escape(md_path)}.md">\n'
           f'<link rel="alternate" type="application/json" href="{html.escape(md_path)}.json">\n</head>')
    return s.replace("</head>", alt, 1)


def noscript(page, md):
    body = f'<noscript><pre class="md-twin">{html.escape(md)}</pre></noscript>'
    return re.sub(r"<noscript>.*?</noscript>", lambda _: body, page, count=1, flags=re.S) if "<noscript>" in page \
        else page.replace("</body>", body + "</body>", 1)


# ------------------------------------------------------------------ llms.txt and the sitemap
def llms(full=False):
    hs = harnesses()["harnesses"]
    tss = tasksets()["tasksets"]
    rn = store.runnable_list()
    lines = ["# Harness Report", "",
             "> Runs AI agent harnesses (Claude Code, Codex, aider, OpenHands, …) straight from their GitHub repos on "
             "Harbor benchmark tasks, in a sandbox, and records every model call. Each harness, taskset, task and run has "
             "a page; add `.md` for Markdown or `.json` for data to any page URL.", "",
             "## How to use this site from an agent", "",
             f"- MCP (streamable HTTP, read-only): {BASE}/mcp — tools: search_tasks, get_task, list_harnesses, get_harness, get_run, recommend_tasks, run_url",
             f"- Harnesses: {BASE}/harnesses.md",
             f"- Tasksets: {BASE}/tasks.md (filter: ?domain=swe)",
             f"- Runnable tasks (startable from the site): {BASE}/api/runnable",
             f"- A run's full record (every model call, logs, files): {BASE}/api/run/<run-id>",
             f"- To evaluate your own harness: sign in at {BASE}/connect, pick the repo, run a task; the site then recommends the next tests for what your harness is for.",
             "", "## Harnesses", ""]
    for h in hs if full else hs[:25]:
        lines.append(f"- [{h['harness']}]({url('harnesses', h['harness'], ext='.md')}): {h.get('passes')}/{h.get('finished')} runs passed"
                     + (f" — {h['use_case']}" if h.get("use_case") else ""))
    lines += ["", "## Runnable tasks", ""]
    for t in rn:
        lines.append(f"- [{t['taskset']}/{t['task']}]({url('tasks', t['taskset'], t['task'], ext='.md')}): {t.get('difficulty') or ''} {t.get('language') or ''}".rstrip())
    lines += ["", "## Tasksets", ""]
    for t in tss if full else [t for t in tss if t.get("n_runnable")] + [t for t in tss if not t.get("n_runnable")][:40]:
        lines.append(f"- [{t['taskset']}]({url('tasks', t['taskset'], ext='.md')}): {t.get('n_tasks')} tasks, {t.get('domain')}")
    if not full: lines += ["", f"Everything: {BASE}/llms-full.txt"]
    return "\n".join(lines) + "\n"


def _urlset(urls):
    body = "".join(f"<url><loc>{html.escape(u)}</loc></url>" for u in urls)
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'


def sitemap(name=None):
    """No name: the index.  'core': the fixed pages, every harness, taskset and run.  'tasks-<taskset>': its tasks."""
    if name is None:
        maps = ["core"] + [f"tasks-{t['taskset']}" for t in store.tasksets_list()]
        body = "".join(f"<sitemap><loc>{BASE}/sitemaps/{quote(m)}.xml</loc></sitemap>" for m in maps)
        return f'<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</sitemapindex>'
    if name == "core":
        urls = [BASE + "/", BASE + "/harnesses", BASE + "/tasks", BASE + "/runs"]
        urls += [url("harnesses", h["harness"]) for h in store.harnesses_list()]
        urls += [url("tasks", t["taskset"]) for t in store.tasksets_list()]
        urls += [url("runs", r["run"]) for r in store.ddb.query(store.RUNLIST, "RUN#", attributes=["run"])]
        return _urlset(urls)
    if name.startswith("tasks-"):
        ts = name[len("tasks-"):]
        rows = store.ddb.query(store.taskset_pk(ts), "TASK#", attributes=["task"])
        if not rows: return None
        return _urlset([url("tasks", ts, r["task"]) for r in rows][:50000])
    return None
