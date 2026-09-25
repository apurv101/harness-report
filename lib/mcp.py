#!/usr/bin/env python3
"""mcp.py — the site as an MCP server, so a coding agent can use Harness Report as a tool.

Streamable HTTP, stateless: every JSON-RPC message is one POST to /mcp and gets one JSON answer (no SSE, no
session id — nothing here needs a stream).  Read-only by design: starting a run spends someone's model budget
and needs a GitHub sign-in, so `run_url` hands back the link a person clicks rather than starting anything.

    initialize · ping · tools/list · tools/call · notifications/* (202, no body)

Every tool answers with the same objects the site's pages are built from (lib/pages.py), as JSON text.
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pages, store                                                     # noqa: E402

PROTOCOL = "2025-06-18"
SERVER = {"name": "harness-report", "version": "1.0.0"}


def _s(desc, **props):
    req = [k for k, v in props.items() if v.pop("required", False)]
    return {"type": "object", "properties": props, "required": req, "additionalProperties": False, "description": desc}


TOOLS = [
    {"name": "search_tasks",
     "description": "Find Harbor benchmark tasks to test an agent harness on. Matches taskset names, domains, languages, "
                    "categories and task instructions. Runnable tasks can be started from harnessreport.com.",
     "inputSchema": _s("", query={"type": "string", "description": "words to match, e.g. 'sql', 'rust bug fix', 'django'"},
                       domain={"type": "string", "description": "a domain facet, e.g. swe, data-sql, finance"},
                       runnable_only={"type": "boolean", "description": "only tasks the site can start (default true)"},
                       limit={"type": "integer", "description": "max results (default 20)"})},
    {"name": "get_task", "description": "One task: its instruction, metadata, and every harness's results on it.",
     "inputSchema": _s("", taskset={"type": "string", "required": True}, task={"type": "string", "required": True})},
    {"name": "list_tasksets", "description": "Every indexed Harbor taskset with its domain, size and how many tasks are runnable.",
     "inputSchema": _s("", domain={"type": "string"})},
    {"name": "list_harnesses", "description": "Every agent harness that has been run here, with pass counts.",
     "inputSchema": _s("")},
    {"name": "get_harness", "description": "One harness: what it is for, how it runs, its results per task, its runs, and the tests recommended next.",
     "inputSchema": _s("", harness={"type": "string", "required": True, "description": "e.g. aider-ai-aider"})},
    {"name": "get_run", "description": "One run's card: harness, task, model, outcome, tests, calls, tokens.",
     "inputSchema": _s("", run={"type": "string", "required": True})},
    {"name": "recommend_tasks", "description": "The tests recommended next for a harness, with a one-line reason each.",
     "inputSchema": _s("", harness={"type": "string", "required": True})},
    {"name": "run_url", "description": "The harnessreport.com link that starts a run of a GitHub repo on a task (a person signs in and clicks Run).",
     "inputSchema": _s("", repo={"type": "string", "required": True, "description": "owner/name"},
                       taskset={"type": "string"}, task={"type": "string"})},
]


def _words(s): return [w for w in re.split(r"[^a-z0-9+#]+", (s or "").lower()) if w]


def search_tasks(query="", domain=None, runnable_only=True, limit=20):
    """Score by word overlap.  The runnable pool is small enough to search whole, instructions included; the full
    corpus is searched at the taskset level, then its first tasks are listed."""
    words = _words(query)
    by_ts = {t["taskset"]: t for t in store.tasksets_list()}

    def score(text):
        text = text.lower()
        return sum(1 for w in words if w in text) if words else 1

    out = []
    for t in store.runnable_list():
        ts = by_ts.get(t["taskset"]) or {}
        if domain and ts.get("domain") != domain: continue
        text = " ".join(str(x) for x in (t["taskset"], t["task"], ts.get("domain"), t.get("language"), t.get("category"),
                                         " ".join(t.get("tags") or []), (t.get("instruction") or "")[:4000]))
        s = score(text)
        if s: out.append((s + 1, {"taskset": t["taskset"], "task": t["task"], "runnable": True, "domain": ts.get("domain"),
                                  "difficulty": t.get("difficulty"), "language": t.get("language"),
                                  "url": pages.url("tasks", t["taskset"], t["task"]),
                                  "harnesses_tried": len(t.get("results") or {})}))
    if not runnable_only:
        for ts in by_ts.values():
            if domain and ts.get("domain") != domain: continue
            text = " ".join(str(x) for x in (ts["taskset"], ts.get("domain"), ts.get("task_kind"), ts.get("name"),
                                             " ".join(ts.get("languages") or []), " ".join(ts.get("categories") or []),
                                             ts.get("sample_instruction") or ""))
            s = score(text)
            if s: out.append((s, {"taskset": ts["taskset"], "runnable": False, "domain": ts.get("domain"),
                                  "n_tasks": ts.get("n_tasks"), "url": pages.url("tasks", ts["taskset"])}))
    out.sort(key=lambda x: -x[0])
    return {"results": [r for _, r in out[:max(1, min(int(limit or 20), 100))]]}


def call(name, args):
    a = args or {}
    if name == "search_tasks":
        return search_tasks(a.get("query", ""), a.get("domain"), a.get("runnable_only", True), a.get("limit", 20))
    if name == "get_task": return pages.task(a["taskset"], a["task"]) or {"error": "no such task"}
    if name == "list_tasksets": return pages.tasksets(a.get("domain"))
    if name == "list_harnesses": return pages.harnesses()
    if name == "get_harness": return pages.harness(a["harness"]) or {"error": "no such harness"}
    if name == "get_run": return pages.run(a["run"]) or {"error": "no such run"}
    if name == "recommend_tasks": return store.harness_recs(a["harness"]) or {"error": "no recommendations yet — run one task first"}
    if name == "run_url":
        from urllib.parse import urlencode
        q = {"repo": a["repo"], **({"taskset": a["taskset"], "task": a["task"]} if a.get("task") else {})}
        return {"url": f"{pages.BASE}/check?{urlencode(q)}", "note": "a person signs in with GitHub and presses Run"}
    raise KeyError(name)


def handle(msg):
    """One JSON-RPC message in, one JSON-RPC response out (None for a notification)."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None: return None                                   # a notification: nothing to answer
    ok = lambda result: {"jsonrpc": "2.0", "id": mid, "result": result}
    if method == "initialize":
        return ok({"protocolVersion": params.get("protocolVersion") or PROTOCOL, "serverInfo": SERVER,
                   "capabilities": {"tools": {"listChanged": False}},
                   "instructions": "Harness Report: find benchmark tasks for an agent harness, see how harnesses did on "
                                   "them, and get the tests recommended next. Read-only; run_url gives the link to start a run."})
    if method == "ping": return ok({})
    if method == "tools/list": return ok({"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        try:
            result = call(name, params.get("arguments"))
        except KeyError as e:
            if name not in {t["name"] for t in TOOLS}:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool {name}"}}
            return ok({"content": [{"type": "text", "text": f"missing argument {e}"}], "isError": True})
        except Exception as e:                                          # the store is down, a bad argument type
            return ok({"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True})
        return ok({"content": [{"type": "text", "text": json.dumps(result, default=str)}], "structuredContent": result})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}


def handle_body(body):
    """A POST body: one message or a batch.  Returns (status, response-or-None)."""
    try: msg = json.loads(body or b"null")
    except ValueError: return 400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
    if isinstance(msg, list):
        out = [r for r in (handle(m) for m in msg) if r is not None]
        return (200, out) if out else (202, None)
    r = handle(msg)
    return (200, r) if r is not None else (202, None)
