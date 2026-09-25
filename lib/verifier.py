#!/usr/bin/env python3
"""verifier.py — what the verifier's output says, parsed once for everyone who needs it.

A Harbor task's tests/test.sh is usually `pytest -v`, and its stdout is the only place the per-test results exist:
reward.txt is one number.  `parse(run_dir)` turns that stdout into passed/failed/total plus the failed names, and
`parse(run_dir, full=True)` adds every test in pytest order with its source (read from the taskset's tests folder)
and its failure traceback.

It lives here rather than in serve.py because two readers need the same answer now — the HTTP API and the
DynamoDB publisher — and a run must not be described differently depending on which one you asked.
"""
import ast, json, os, re

TEST_LINE = re.compile(r"^(\S+::[^\n]+?)\s+(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b", re.M)
# pytest -rA's "short test summary info": the only per-test lines a verifier that runs pytest without -v prints
SHORT_LINE = re.compile(r"^(PASSED|FAILED|ERROR|XFAIL|XPASS) (\S+::\S+)(?: - .*)?$", re.M)
TEST_SUMMARY = re.compile(r"^=+ (.*?(?:passed|failed|error)[^=]*?) in [\d.]+s .*=+$", re.M)
FAIL_HEAD = re.compile(r"^_+\s+(.+?)\s+_+$", re.M)


def _read(path, default=None):
    try:
        with open(path, encoding="utf-8", errors="replace") as f: return f.read()
    except OSError: return default


def test_details(out, names):
    """Keep complete pytest report blocks, including captured output, on the right test.

    Class names and parameter IDs matter: two tests with the same function name must
    never inherit each other's traceback. Ambiguous blocks remain in the suite log.
    """
    details = {}
    sections = re.finditer(r"^=+ (?:FAILURES|ERRORS|PASSES|XFAILURES|XPASSES) =+\n(.*?)(?=^=+ .* =+$|\Z)", out, re.M | re.S)
    for section in sections:
        parts = FAIL_HEAD.split(section.group(1))
        for i in range(1, len(parts) - 1, 2):
            title, body = parts[i], parts[i + 1].strip()
            label = re.sub(r"^ERROR at (?:setup|teardown) of ", "", title)
            matches = [n for n in names if label in (n, ".".join(n.split("::")[1:]), n.split("::")[-1])]
            if len(matches) > 1:
                matches = [n for n in matches if re.search(r"^" + re.escape(n.split("::")[0]) + r":\d+:", body, re.M)]
            if len(matches) == 1:
                details.setdefault(matches[0], []).append(title + "\n" + body)
    return {name: "\n\n".join(blocks) for name, blocks in details.items()}


def test_sources(tdir):
    """{basename: {function name: source}} for every python test file in the task's tests folder."""
    src = {}
    for root, _, fs in os.walk(tdir):
        for f in fs:
            if not f.endswith(".py"): continue
            code = _read(os.path.join(root, f))
            if code is None: continue
            try: tree = ast.parse(code)
            except SyntaxError: continue
            lines = code.splitlines(); funcs = {}
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                    start = min([node.lineno] + [x.lineno for x in node.decorator_list])
                    funcs[node.name] = "\n".join(lines[start - 1:node.end_lineno])
            src[f] = funcs
    return src


def parse(d, full=False):
    """Per-test results from verifier/stdout.log: passed/failed/total, the failed test names, and pytest's own
    summary line.  None when there is no such output.  full=True adds `cases`: every test in pytest order with its
    result, its source from the task's tests folder, and its failure traceback."""
    out = _read(os.path.join(d, "verifier", "stdout.log"))
    if not out: return None
    out = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", out).replace("\r\n", "\n")
    found = TEST_LINE.findall(out)
    seen = {n for n, _ in found}
    found += [(n, r) for r, n in SHORT_LINE.findall(out) if n not in seen]
    summ = TEST_SUMMARY.findall(out)
    # pytest aborted before running anything (e.g. a file the agent left behind failed at import): report that, not 0 tests
    aborted = re.search(r"^!+ Interrupted: (.*?) !+$", out, re.M)
    if aborted and not found:
        bad = re.findall(r"^_+ ERROR collecting (\S+) _+$", out, re.M)
        return {"passed": 0, "failed": 0, "total": 0, "failed_names": [], "agent_written": 0, "cases": [] if full else None,
                "aborted": aborted.group(1) + (": " + ", ".join(bad) if bad else ""), "summary": summ[-1] if summ else None}
    if not found and not summ: return None
    by = {}
    for name, res in found: by[name] = res          # a test reported twice keeps its last result
    # Only the task's own test files count: pytest also collects any test files the agent left in the workdir.
    # The task folder (run.json task.taskset_dir/task.name) says which files are official, when it is readable.
    try:
        with open(os.path.join(d, "run.json")) as f: rj = json.load(f)
    except (OSError, ValueError): rj = {}
    t = rj.get("task") or {}
    official = None; tdir = None
    if t.get("taskset_dir") and t.get("name"):
        tdir = os.path.join(t["taskset_dir"], t["name"], "tests")
        if os.path.isdir(tdir): official = {f for _, _, fs in os.walk(tdir) for f in fs}
        else: tdir = None
    own = {n: r for n, r in by.items() if official is None or os.path.basename(n.split("::")[0]) in official}
    extra = len(by) - len(own)
    failed = sorted(n.split("::")[-1] for n, r in own.items() if r in ("FAILED", "ERROR"))
    passed = sum(1 for r in own.values() if r in ("PASSED", "XPASS"))
    res = {"passed": passed, "failed": len(failed), "total": len(own), "failed_names": failed, "agent_written": extra,
           "summary": summ[-1] if summ else None}
    if aborted: res["aborted"] = aborted.group(1)
    if full:
        det = test_details(out, by); src = test_sources(tdir) if tdir else {}
        res["cases"] = [{"id": n, "name": "::".join(n.split("::")[1:]), "file": n.split("::")[0], "result": r,
                         "own": n in own, "detail": det.get(n),
                         "source": src.get(os.path.basename(n.split("::")[0]), {}).get(n.split("::")[-1].split("[")[0])} for n, r in by.items()]
    return res
