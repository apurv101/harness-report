#!/usr/bin/env python3
"""report.py — everything run.sh prints for a person to read, rather than for a machine to parse.

    report.py runs <runs-dir> <regex>        one line per run folder, from its run.json
    report.py view <calls.jsonl>             the recorded model calls, rendered as a conversation
    report.py summary <batch.jsonl> <k>      the task x k reward table at the end of a Harbor sweep

Called by lib/report.sh.  Each reads files a run already wrote; none of them touches Docker or the network.
"""
import collections, json, os, re, sys


def runs(args):
    """`run.sh runs`: one line per run folder, newest first, those whose name matches the regex."""
    root, pat = args
    rows = []
    for d in sorted(os.listdir(root) if os.path.isdir(root) else [], reverse=True):
        p = os.path.join(root, d, "run.json")
        if not os.path.isfile(p) or (pat and not re.search(pat, d)): continue
        r = json.load(open(p)); t = r.get("task") or {}
        rows.append((d, r.get("kind", "?"), (r.get("harness") or {}).get("name", "?"), t.get("name") or (r.get("prompt") or "")[:40].replace("\n", " "),
                     (r.get("model") or "").split("/")[-1][:28], "-" if r.get("rc") is None else r["rc"], "-" if r.get("reward") is None else r["reward"],
                     "-" if r.get("seconds") is None else f"{r['seconds']}s", "-" if r.get("calls") is None else r["calls"], "" if r.get("finished") else "(unfinished)"))
    if not rows: sys.exit("no runs" + (f" matching {pat!r}" if pat else "") + f" in {root}")
    hdr = ["run", "kind", "harness", "task", "model", "rc", "reward", "time", "calls", ""]
    w = [max([len(hdr[i])] + [len(str(x[i])) for x in rows]) for i in range(len(hdr))]
    print("  ".join(h.ljust(w[i]) for i, h in enumerate(hdr)).rstrip())
    for x in rows: print("  ".join(str(v).ljust(w[i]) for i, v in enumerate(x)).rstrip())


def view(args):
    """`run.sh view <dir>`: the last recorded request, and its response, as SYSTEM / USER / ASSISTANT turns."""
    calls = [json.loads(l) for l in open(args[0]) if l.strip()]
    if not calls: sys.exit("no calls recorded")
    tin = sum(c["usage"].get("input_tokens") or 0 for c in calls); tout = sum(c["usage"].get("output_tokens") or 0 for c in calls)
    errs = sum(1 for c in calls if c.get("error"))
    print(f"{len(calls)} model calls   route={calls[0]['route']}   model={calls[0]['model']}   tokens in={tin} out={tout}   errors={errs}")
    print("-" * 78)
    last = calls[-1]; req = last["request"]; route = last["route"]
    def text(c):
        if isinstance(c, str): return c
        return "\n".join(p.get("text", json.dumps(p)) if isinstance(p, dict) and p.get("type") in ("text", None) else json.dumps(p) for p in (c or []))
    def clip(s, n=500): s = s.strip(); return s if len(s) <= n else s[:n] + f" … [{len(s)-n} more]"
    if route == "openai":
        sysm = [m for m in req["messages"] if m["role"] in ("system", "developer")]
        for m in sysm: print("SYSTEM\n    " + clip(text(m["content"]), 300).replace("\n", "\n    ") + "\n")
        for m in req["messages"]:
            r = m["role"]
            if r in ("system", "developer"): continue
            if r == "assistant":
                t = text(m.get("content")); print("ASSISTANT");
                if t.strip(): print("    " + clip(t).replace("\n", "\n    "))
                for tc in m.get("tool_calls") or []:
                    a = tc["function"]["arguments"]
                    try: a = json.loads(a); a = a.get("command") or a.get("cmd") or a.get("code") or json.dumps(a)
                    except Exception: pass
                    print("    $ " + str(a).replace("\n", "\n      "))
            elif r == "tool": print("OBSERVATION\n    " + clip(text(m.get("content"))).replace("\n", "\n    "))
            else: print("USER\n    " + clip(text(m.get("content"))).replace("\n", "\n    "))
            print()
        rm = last["response"]["choices"][0]["message"] if last.get("response") else {}
        print("ASSISTANT (final)"); print("    " + clip(text(rm.get("content") or "")).replace("\n", "\n    "))
        for tc in rm.get("tool_calls") or []: print("    $ " + tc["function"]["arguments"])
    else:
        if req.get("system"): print("SYSTEM\n    " + clip(text(req["system"]), 300).replace("\n", "\n    ") + "\n")
        for m in req["messages"]:
            print(m["role"].upper())
            for b in (m["content"] if isinstance(m["content"], list) else [{"type": "text", "text": m["content"]}]):
                t = b.get("type")
                if t == "text": print("    " + clip(b["text"]).replace("\n", "\n    "))
                elif t == "tool_use": print("    $ " + json.dumps(b.get("input")))
                elif t == "tool_result": print("    → " + clip(text(b.get("content"))).replace("\n", "\n    "))
            print()
        print("ASSISTANT (final)")
        for b in (last.get("response") or {}).get("content", []):
            if b.get("type") == "text": print("    " + clip(b["text"]).replace("\n", "\n    "))
            elif b.get("type") == "tool_use": print("    $ " + json.dumps(b.get("input")))


def summary(args):
    """The end of a Harbor sweep: a row per task, a column per k, and the pass counts."""
    rows = [json.loads(l) for l in open(args[0]) if l.strip()]; k = int(args[1])
    by = collections.OrderedDict()
    for r in rows: by.setdefault(r["task"], {})[r["k"]] = r
    w = max([len(t) for t in by] + [4])
    print(f"{'task':<{w}}  " + "  ".join(f"k{i}" for i in range(1, k + 1)) + "   pass")
    tot = ok = 0; allpass = 0
    for t, ks in by.items():
        cells = []; n = 0
        for i in range(1, k + 1):
            r = ks.get(i); v = r["reward"] if r else None
            cells.append(" -" if v is None else f"{v:>2}" if isinstance(v, int) else f"{v:.1f}")
            if v is not None: tot += 1; n += 1 if v else 0
        ok += n; allpass += 1 if n == k else 0
        print(f"{t:<{w}}  " + "  ".join(cells) + f"   {n}/{k}")
    print(f"\nrewarded runs {ok}/{tot}   tasks passing all k {allpass}/{len(by)}")


if __name__ == "__main__":
    {"runs": runs, "view": view, "summary": summary}[sys.argv[1]](sys.argv[2:])
