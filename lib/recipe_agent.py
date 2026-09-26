#!/usr/bin/env python3
"""recipe_agent.py — the analyze stage as a tool loop.  A model reads the harness repo, writes a recipe, builds it,
runs the harness from it through the recording proxy on a real task, reads what happened, and changes the recipe
until the harness is shown to reach the model; then it hands back that recipe.  lib/recipe.sh runs this instead
of `claude -p` when ANALYZER=agent.

    recipe_agent.py --src <clone> --repo-url <url> --commit <sha> --name <name> --work <dir> --out <analyze.raw.json>
                    [--task-dir <harbor task> --task-image <image>] [--seed <recipe.json> --seed-commit <sha>]
                    [--feedback <file> --previous <recipe.json>]

Every Docker action goes through lib/trial.sh, which reuses run.sh's build_overlay, start_proxy and agent_phase.
The standing contract is lib/analyze-prompt.md, the same one claude -p gets; lib/recipe-agent-prompt.md adds the
tools and what counts as proof.  Under <work>: transcript.jsonl (every model turn and tool result), builds/<n>/,
trials/<n>/ (each harness run's proxy record and logs) and verdict.json.

Exit 0: <out> holds {"structured_output": <recipe>, ...}, the shape `recipe.py save` reads from claude -p.
Exit 3: the model showed the harness cannot run here; the reason is in <work>/verdict.json and on stderr.
Exit 1: turns, time or spend ran out, or the model API failed.  Progress goes to stderr.

Settings, from the environment (.env):
  RECIPE_AGENT_MODEL        bedrock/<inference profile> or anthropic/<model>; default bedrock/us.anthropic.claude-fable-5-1
  RECIPE_AGENT_FALLBACK     serves a request the model refuses, and the rest of the session after it;
                            default bedrock/us.anthropic.claude-opus-5
  RECIPE_AGENT_AWS_PROFILE  AWS profile for bedrock/ targets (default AWS_PROFILE; unset on EC2 = the instance role)
  RECIPE_AGENT_EFFORT       low | medium | high | xhigh | max (default high)
  RECIPE_AGENT_MAX_TURNS (80)  RECIPE_AGENT_MAX_USD (25, at list price)  RECIPE_AGENT_MAX_SECONDS (5400)
"""
import argparse, copy, fnmatch, json, os, re, signal, subprocess, sys, time
from collections import Counter
from pathlib import Path

import recipe as recipes

HERE = Path(__file__).resolve().parents[1]
TRIAL = HERE / "lib" / "trial.sh"
SCHEMA = json.loads((HERE / "lib" / "recipe-schema.json").read_text())
SETUP = [k for k in SCHEMA["properties"] if k not in ("summary", "notes")]
PROBE = "Create a file named hello.txt in the current directory containing the single word hello. Then stop.\n"
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".trial"}   # .trial: a trial's wrapper and proxy build context
COMPOSE = ("docker-compose.yaml", "docker-compose.yml", "compose.yaml", "compose.yml")
# list price per million tokens (input, output, cache write, cache read): the spend cap's estimate, not the bill
PRICES = [("fable-5-1", (10, 50, 12.5, 0.25)), ("fable-5", (10, 50, 12.5, 1.0)), ("opus-5-5", (4, 20, 5, 0.2)),
          ("opus-5", (5, 25, 6.25, 0.5)), ("sonnet-5", (2, 10, 2.5, 0.2)), ("sonnet-4-6", (3, 15, 3.75, 0.3)),
          ("sonnet-4-5", (3, 15, 3.75, 0.3)), ("haiku-4-5", (1, 5, 1.25, 0.1))]
# Bedrock serves these on the stack that takes top-level cache_control; older models there need explicit breakpoints
TOP_LEVEL_CACHE = ("fable", "mythos", "opus-5", "opus-4-7", "opus-4-8", "sonnet-5")


def say(msg): print(msg, file=sys.stderr, flush=True)


def leaf_changes(lines):
    """docker diff without the noise: parent directories of other changes, bytecode caches, and the mounts."""
    keep = [l for l in lines if len(l) > 2 and not re.search(r"/__pycache__(/|$)|\.pyc$", l)
            and not re.match(r"[ACD] /(proc|sys|dev|run|task|logs|out|root/\.cache|usr/local/bin/run-harness)(/|$)", l)]
    parents = {str(a) for l in lines for a in Path(l[2:]).parents}
    return [l for l in keep if l[2:] not in parents]


def tail(text, n): return text if len(text) <= n else "…" + text[-n:]


class ToolError(Exception): pass


def trial(*args, timeout):
    """lib/trial.sh <args>, in its own process group so a timeout can stop its containers through its EXIT trap."""
    p = subprocess.Popen(["bash", str(TRIAL), *map(str, args)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, errors="replace", start_new_session=True)
    try: out = p.communicate(timeout=timeout)[0]
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGTERM)
        try: out = p.communicate(timeout=30)[0]
        except subprocess.TimeoutExpired: os.killpg(p.pid, signal.SIGKILL); out = p.communicate()[0]
        return 124, f"{out}\n(trial.sh stopped after {timeout} s)"
    return p.returncode, out


def connect(target):
    """'bedrock/<id>' or 'anthropic/<id>' -> (client, model id)."""
    import anthropic
    kind, _, model = target.partition("/")
    if kind == "bedrock":
        profile = os.environ.get("RECIPE_AGENT_AWS_PROFILE") or os.environ.get("AWS_PROFILE") or None
        return anthropic.AnthropicBedrock(aws_region=os.environ.get("AWS_REGION", "us-west-2"), aws_profile=profile,
                                          timeout=900, max_retries=4), model
    if kind == "anthropic" and model:
        return anthropic.Anthropic(timeout=900, max_retries=4), model
    sys.exit(f"recipe agent: a model target is bedrock/<id> or anthropic/<id>, not {target!r}")


def mark_cache(messages):
    """Explicit breakpoints on the newest user turn, for models that refuse top-level cache_control (the system block
    carries the other one); the previous turn's marker is moved, so a request never holds more than two."""
    for m in messages:
        if m["role"] == "user" and isinstance(m["content"], list):
            for b in m["content"]: b.pop("cache_control", None)
    if isinstance(messages[-1]["content"], str): messages[-1]["content"] = [{"type": "text", "text": messages[-1]["content"]}]
    messages[-1]["content"][-1]["cache_control"] = {"type": "ephemeral"}


def cost(model, usage):
    price = next((p for key, p in PRICES if key in model), None)
    if not price: return 0.0
    counts = (usage.input_tokens, usage.output_tokens, usage.cache_creation_input_tokens or 0, usage.cache_read_input_tokens or 0)
    return sum(c * p for c, p in zip(counts, price)) / 1e6


BUILD_INPUT = {"type": "object", "required": [k for k in SCHEMA["required"] if k in SETUP],
               "properties": copy.deepcopy({k: SCHEMA["properties"][k] for k in SETUP})}
ROOT = {"type": "string", "enum": ["repo", "trials"], "description": "repo (default) or trials, the output of your run_harness calls"}
TOOLS = [
    {"name": "read_file", "description": "A text file under the root, with line numbers.",
     "input_schema": {"type": "object", "required": ["path"], "properties": {
         "path": {"type": "string", "description": "relative to the root, e.g. README.md or 3/stdout.log"}, "root": ROOT,
         "offset": {"type": "integer", "description": "first line to return, 1-based (default 1)"},
         "limit": {"type": "integer", "description": "number of lines (default 400, at most 2000)"}}}},
    {"name": "list_files", "description": "Paths under the root that match a glob, such as **/*.toml or src/*.",
     "input_schema": {"type": "object", "required": ["pattern"], "properties": {"pattern": {"type": "string"}, "root": ROOT}}},
    {"name": "search", "description": "Lines matching a regular expression (Python syntax) in the files under the root, as path:line: text.",
     "input_schema": {"type": "object", "required": ["pattern"], "properties": {
         "pattern": {"type": "string"}, "root": ROOT, "glob": {"type": "string", "description": "only files whose relative path matches, e.g. *.py"},
         "ignore_case": {"type": "boolean"}}}},
    {"name": "build", "description": "Build this recipe the way the pipeline does: the overlay FROM base_image (target base) and, "
     "when there is a benchmark task, FROM the task image (target task), with check_command run in each with no network. "
     "Returns the build number and, for a failure, the end of the build or check log.", "input_schema": BUILD_INPUT},
    {"name": "run_harness", "description": "Run the harness from the latest build through the recording proxy and a real model, "
     "started exactly as an evaluation starts it. base: a small probe task in the base-image overlay. task: the first benchmark "
     "task in the task-image overlay. Returns its model calls, exit code, output and changed files; the files stay under trials/<n>/.",
     "input_schema": {"type": "object", "required": ["target"], "properties": {
         "target": {"type": "string", "enum": ["base", "task"]},
         "timeout_seconds": {"type": "integer", "description": "stop the harness after this long (default 600, 60 to 1800)"}}}},
    {"name": "run_in_image", "description": "One bash command in a fresh container of a built overlay (base, task) or any image reference.",
     "input_schema": {"type": "object", "required": ["image", "command"], "properties": {
         "image": {"type": "string", "description": "base, task, or an image such as python:3.12-slim"},
         "command": {"type": "string"}, "network": {"type": "string", "enum": ["none", "open"], "description": "default none"},
         "timeout_seconds": {"type": "integer", "description": "default 120, at most 900"}}}},
    {"name": "submit", "description": "Hand back a build as the recipe. Accepted only if all its targets built and passed their "
     "check and run_harness on it reached the model on the target that matters.",
     "input_schema": {"type": "object", "required": ["summary"], "properties": {
         "build": {"type": "integer", "description": "build number (default: the latest)"},
         "summary": {"type": "string", "description": SCHEMA["properties"]["summary"]["description"]},
         "notes": {"type": "string", "description": "what the proving run showed, and anything a reader needs to know about the configuration"}}}},
    {"name": "give_up", "description": "End the session: the harness cannot run one task non-interactively against the proxy here.",
     "input_schema": {"type": "object", "required": ["reason"], "properties": {
         "reason": {"type": "string", "description": "what you found, with the evidence"}}}},
]


class Session:
    """The agent's machine: the clone to read, the builds and harness runs it made, and whether it has finished."""

    def __init__(self, a):
        self.a, self.src, self.work = a, Path(a.src).resolve(), Path(a.work).resolve()
        (self.work / "trials").mkdir(parents=True, exist_ok=True)
        self.builds, self.trials, self.result = [], [], None
        self.task_dir = Path(a.task_dir).resolve() if a.task_dir else None
        self.targets = ["base"] + (["task"] if a.task_image else [])
        compose = self.task_dir and any((self.task_dir / "environment" / f).is_file() for f in COMPOSE)
        # a Compose task's services are not started for a trial, so its proof comes from the probe
        self.required = "task" if a.task_image and not compose else "base"
        self.task_workdir = "/app"
        if a.task_image:
            wd = subprocess.run(["docker", "image", "inspect", "-f", "{{.Config.WorkingDir}}", a.task_image], capture_output=True, text=True).stdout.strip()
            self.task_workdir = wd or "/app"
        self.probe = self.work / "probe.md"; self.probe.write_text(PROBE)

    def call(self, name, inp):
        fn = {"read_file": self.read_file, "list_files": self.list_files, "search": self.search, "build": self.build,
              "run_harness": self.run_harness, "run_in_image": self.run_in_image, "submit": self.submit, "give_up": self.give_up}.get(name)
        if not fn: raise ToolError(f"no tool {name}")
        return fn(inp)

    # ---------------------------------------------------------------- reading
    def root(self, inp):
        return self.src if inp.get("root", "repo") == "repo" else self.work / "trials"

    def resolve(self, inp, path):
        base = self.root(inp); p = (base / path).resolve()
        if p != base and base not in p.parents: raise ToolError(f"{path} is outside the {inp.get('root', 'repo')} root")
        if not p.exists(): raise ToolError(f"no such file: {path}")
        return p

    def read_file(self, inp):
        p = self.resolve(inp, inp["path"])
        if p.is_dir(): return "\n".join(sorted(c.name + ("/" if c.is_dir() else "") for c in p.iterdir())) or "(empty directory)"
        data = p.read_bytes()
        if b"\0" in data[:8192]: return f"(binary file, {len(data)} bytes)"
        lines = data.decode("utf-8", "replace").splitlines()
        start = max(1, int(inp.get("offset") or 1)); n = min(2000, max(1, int(inp.get("limit") or 400)))
        out = [f"{i:6}\t{l[:2000]}" for i, l in enumerate(lines[start - 1:start - 1 + n], start)]
        more = len(lines) - (start - 1 + n)
        return "\n".join(out) + (f"\n… {more} more lines (offset={start + n})" if more > 0 else "") if out else f"(file has {len(lines)} lines)"

    def walk(self, base):
        for d, dirs, files in os.walk(base):
            dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
            for f in sorted(files): yield Path(d, f)

    def list_files(self, inp):
        base = self.root(inp); pat = inp["pattern"]
        hits = [p.relative_to(base).as_posix() for p in self.walk(base) if fnmatch.fnmatch(p.relative_to(base).as_posix(), pat)
                or ("/" not in pat and fnmatch.fnmatch(p.name, pat))]
        return "\n".join(hits[:300]) + (f"\n… {len(hits) - 300} more" if len(hits) > 300 else "") if hits else "no matches"

    def search(self, inp):
        base = self.root(inp)
        try: rx = re.compile(inp["pattern"], re.I if inp.get("ignore_case") else 0)
        except re.error as e: raise ToolError(f"bad pattern: {e}")
        hits = []
        for i, p in enumerate(self.walk(base)):
            rel = p.relative_to(base).as_posix()
            if i > 20000 or len(hits) >= 200: break
            if inp.get("glob") and not (fnmatch.fnmatch(rel, inp["glob"]) or fnmatch.fnmatch(p.name, inp["glob"])): continue
            try:
                if p.stat().st_size > 2_000_000: continue
                data = p.read_bytes()
            except OSError: continue
            if b"\0" in data[:8192]: continue
            for n, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{rel}:{n}: {line.strip()[:300]}")
                    if len(hits) >= 200: break
        return "\n".join(hits) + ("\n… stopped at 200 matches" if len(hits) >= 200 else "") if hits else "no matches"

    # ---------------------------------------------------------------- the machine
    def tag(self, target): return f"hr-agent/{self.a.name}:{target}"

    def build(self, inp):
        r = {k: inp[k] for k in SETUP if k in inp}
        missing = [k for k in BUILD_INPUT["required"] if k not in r]
        if missing: raise ToolError(f"missing fields: {', '.join(missing)}")
        if err := recipes.overlay_error(r["dockerfile"]): raise ToolError(err)
        if not isinstance(r["env"], list) or not all(isinstance(e, dict) and {"name", "value"} <= set(e) for e in r["env"]):
            raise ToolError("env must be a list of {name, value} objects")
        b = {"n": len(self.builds) + 1, "recipe": r, "ok": {}}
        d = self.work / "builds" / str(b["n"]); d.mkdir(parents=True)
        b["path"] = d / "recipe.json"; b["path"].write_text(json.dumps(r, indent=2))
        self.builds.append(b)
        parts = [f"build {b['n']}"]
        for target in self.targets:
            base = r["base_image"] if target == "base" else self.a.task_image
            if False in b["ok"].values():
                b["ok"][target] = False; parts.append(f"{target}: not attempted, an earlier target failed"); continue
            say(f"   building {target} FROM {base}")
            rc, out = trial("build", b["path"], self.src, self.a.commit, base, self.tag(target), d / target, timeout=3600)
            b["ok"][target] = rc == 0
            check = d / target / "check.log"
            detail = f"check output (end):\n{tail(check.read_text(errors='replace'), 1500)}" if rc == 0 and check.exists() else tail(out, 8000)
            parts.append(f"{target} (FROM {base}): {'built, check passed' if rc == 0 else 'FAILED'}\n{detail}")
        say(f"   build {b['n']}: " + ", ".join(f"{t} {'ok' if ok else 'failed'}" for t, ok in b["ok"].items()))
        return "\n\n".join(parts)

    def run_harness(self, inp):
        target = inp["target"]
        if target not in self.targets: raise ToolError("there is no benchmark task here; use target base")
        if not self.builds or not self.builds[-1]["ok"].get(target):
            raise ToolError(f"the latest build has no working {target} overlay; build first")
        b = self.builds[-1]; secs = min(1800, max(60, int(inp.get("timeout_seconds") or 600)))
        t = {"n": len(self.trials) + 1, "build": b["n"], "target": target}
        out = self.work / "trials" / str(t["n"]); out.mkdir(parents=True)
        if target == "task": workdir, instr, tdir = self.task_workdir, self.task_dir / "instruction.md", self.task_dir
        else: workdir, instr, tdir = b["recipe"].get("workdir") or "/work", self.probe, ""
        say(f"   trial {t['n']}: build {b['n']} {target}, cwd {workdir}, up to {secs} s")
        rc, text = trial("run", b["path"], self.tag(target), workdir, instr, out, secs, tdir, timeout=secs + 600)
        report = self.summarize(t, out, rc, text, secs)
        self.trials.append(t)
        say(f"   trial {t['n']}: {t['calls']} model calls ({t['answered']} answered), harness exit {t['rc']}")
        return report

    def summarize(self, t, out, rc, text, secs):
        """What a harness run did, from its own files: calls.jsonl, egress.jsonl, changes.txt, stdout and stderr."""
        m = re.search(r"rc=(\d+) seconds=(\d+)", text)
        t["rc"], seconds = (int(m[1]), int(m[2])) if m else (None, None)
        calls = [json.loads(l) for l in (out / "calls.jsonl").read_text().splitlines() if l.strip()] if (out / "calls.jsonl").exists() else []
        t["calls"], t["answered"] = len(calls), sum(1 for c in calls if not c.get("error"))
        lines = [f"trial {t['n']}: build {t['build']}, target {t['target']}"]
        if m is None: lines.append(f"the trial did not reach the harness (trial.sh exit {rc}):\n{tail(text, 4000)}")
        else: lines.append(f"harness exit code {t['rc']} after {seconds} s" + (f" (stopped at the {secs} s limit)" if t["rc"] in (124, 142) else ""))
        kinds = Counter(f"{c.get('route')} {c.get('path')} model={c.get('model_requested')}" for c in calls)
        lines.append(f"model calls: {t['calls']} reached the proxy, {t['answered']} answered" + "".join(f"\n  {n} × {k}" for k, n in kinds.items()))
        for c in [c for c in calls if c.get("error")][:3]: lines.append(f"  error on call {c.get('n')}: {str(c['error'])[:600]}")
        if (out / "egress.jsonl").exists():
            eg = [json.loads(l) for l in (out / "egress.jsonl").read_text().splitlines() if l.strip()]
            refused = Counter(e.get("host") for e in eg if not e.get("allowed"))
            if refused: lines.append("outbound connections refused by the sandbox: " + ", ".join(f"{h} ×{n}" for h, n in refused.most_common(10)))
        if (out / "changes.txt").exists():
            ch = leaf_changes((out / "changes.txt").read_text().splitlines())
            lines.append("files changed in the container (docker diff): " + ("\n  " + "\n  ".join(ch[:40]) + (f"\n  … {len(ch) - 40} more" if len(ch) > 40 else "") if ch else "none"))
        for f in ("stdout.log", "stderr.log"):
            body = (out / f).read_text(errors="replace").strip() if (out / f).exists() else ""
            lines.append(f"{f} (end):\n{tail(body, 3000)}" if body else f"{f}: empty")
        lines.append(f"files: trials/{t['n']}/ " + " ".join(sorted(p.name for p in out.iterdir() if not p.name.startswith("."))))
        return "\n".join(lines)

    def run_in_image(self, inp):
        image = inp["image"]
        if image in ("base", "task"):
            if not self.builds or not self.builds[-1]["ok"].get(image): raise ToolError(f"the latest build has no working {image} overlay")
            image = self.tag(image)
        elif not re.fullmatch(r"[\w][\w./:@-]*", image): raise ToolError(f"not an image reference: {image}")
        secs = min(900, max(10, int(inp.get("timeout_seconds") or 120)))
        rc, out = trial("exec", image, inp.get("network") or "none", secs, inp["command"], timeout=secs + 300)
        return f"exit code {rc}\n{tail(out, 12000)}"

    # ---------------------------------------------------------------- the end
    def submit(self, inp):
        if not self.builds: raise ToolError("nothing has been built yet")
        n = int(inp.get("build") or len(self.builds))
        if not 1 <= n <= len(self.builds): raise ToolError(f"there is no build {n}")
        b = self.builds[n - 1]
        problems = [f"target {t} did not build and pass its check" for t in self.targets if not b["ok"].get(t)]
        proof = next((t for t in self.trials if t["build"] == n and t["target"] == self.required and t["calls"]), None)
        if not proof: problems.append(f"no run_harness on build {n} with target {self.required} has reached the model yet")
        if problems: raise ToolError(f"build {n} is not proven: " + "; ".join(problems))
        self.result = ("submit", {**b["recipe"], "summary": inp["summary"], "notes": inp.get("notes", "")}, b, proof)
        return f"accepted build {n}"

    def give_up(self, inp):
        self.result = ("give_up", inp["reason"])
        return "recorded"


def contract(a):
    """The standing analyze prompt, which ends where claude -p's repository tree is appended, and the agent's part."""
    body = (HERE / "lib" / "analyze-prompt.md").read_text().replace("{{REPO_URL}}", a.repo_url)
    body = body.rstrip().removesuffix("Repository tree (2 levels):").rstrip()
    return body + "\n\n" + (HERE / "lib" / "recipe-agent-prompt.md").read_text()


def first_message(a, s):
    tree = sorted(p.relative_to(s.src).as_posix() for p in [*s.src.glob("*"), *s.src.glob("*/*")]
                  if p.relative_to(s.src).parts[0] not in (".git", "node_modules"))
    parts = [f"Package {a.repo_url} at commit {a.commit}."]
    if a.task_image:
        parts.append(f"Evaluations run it on Harbor benchmark tasks. The first is {s.task_dir.parent.name}/{s.task_dir.name}; its image "
                     f"{a.task_image} is built, and its working directory is {s.task_workdir}. run_harness target task runs it. "
                     f"submit needs a {s.required} run that reached the model"
                     + ("" if s.required == "task" else " (this task has Compose services, which a trial does not start)") + ".")
        df = s.task_dir / "environment" / "Dockerfile"
        if df.exists():
            lines = [l for l in df.read_text().splitlines() if l.strip() and not l.strip().startswith("#")][:40]
            parts.append("The overlay is also built FROM that task image. Its Dockerfile, comments stripped:\n" + "\n".join(lines))
        instr = s.task_dir / "instruction.md"
        if instr.exists(): parts.append("The task's instruction, which the harness receives as $TASK:\n" + tail(instr.read_text(), 3000))
    else:
        parts.append("Evaluations run it on ad-hoc tasks in the base-image overlay, in the recipe's workdir (default /work). "
                     "submit needs a base run that reached the model.")
    parts.append("Repository tree (2 levels):\n" + "\n".join(tree[:150]))
    if a.seed and not a.feedback:
        parts.append(f"A RECIPE FOR AN EARLIER COMMIT OF THIS REPO ({a.seed_commit}) BUILT, PASSED ITS CHECK AND RAN. This clone is at "
                     f"{a.commit}. Start from it and keep it unchanged unless this commit changed something it depends on (the entrypoint "
                     "or CLI flags, manifests or lockfiles, build steps, runtime versions, env variables, config file formats). Results are "
                     "compared across commits, so an unneeded change to the Docker setup is a cost, not an improvement.\n" + Path(a.seed).read_text())
    if a.feedback:
        parts.append("A RECIPE FROM AN EARLIER SESSION FAILED THE PIPELINE'S OWN BUILD AND CHECK. Fix it. "
                     + (f"That recipe:\n{Path(a.previous).read_text()}\n" if a.previous and Path(a.previous).exists() else "")
                     + "The error:\n" + Path(a.feedback).read_text())
    return "\n\n".join(parts)


def narrate(content):
    for b in content:
        if b.type == "thinking" and b.thinking: say("   thinking: " + " ".join(b.thinking.split())[:300])
        elif b.type == "text" and b.text.strip(): say("   " + " ".join(b.text.split())[:500])


def brief(name, inp):
    if name in ("read_file", "list_files", "search"): return f"{name} {inp.get('root', 'repo')}:{inp.get('path') or inp.get('pattern')}"
    if name == "build": return f"build (base {inp.get('base_image')})"
    if name == "run_harness": return f"run_harness {inp.get('target')}"
    if name == "run_in_image": return f"run_in_image {inp.get('image')}: {' '.join(str(inp.get('command')).split())[:160]}"
    return name


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for f in ("src", "repo-url", "commit", "name", "work", "out"): ap.add_argument("--" + f, required=True)
    for f in ("task-dir", "task-image", "seed", "seed-commit", "feedback", "previous"): ap.add_argument("--" + f)
    a = ap.parse_args()
    import anthropic   # here, not at the top: the tools and the gate import without the SDK (tests, CI)
    s = Session(a)
    env = os.environ.get
    primary = env("RECIPE_AGENT_MODEL") or "bedrock/us.anthropic.claude-fable-5-1"
    fallback = env("RECIPE_AGENT_FALLBACK") or "bedrock/us.anthropic.claude-opus-5"
    effort = env("RECIPE_AGENT_EFFORT") or "high"
    max_turns, max_usd, max_s = int(env("RECIPE_AGENT_MAX_TURNS") or 80), float(env("RECIPE_AGENT_MAX_USD") or 25), int(env("RECIPE_AGENT_MAX_SECONDS") or 5400)
    (client, model), label = connect(primary), primary
    system = [{"type": "text", "text": contract(a)}]
    messages = [{"role": "user", "content": first_message(a, s)}]
    log = open(s.work / "transcript.jsonl", "a")
    log.write(json.dumps({"system": system[0]["text"], "user": messages[0]["content"], "model": primary}) + "\n")
    spend, t0, nudges, served = 0.0, time.time(), 0, [model]
    say(f"recipe agent: {primary} (effort {effort}), work {s.work}")

    def stop(code, why):
        verdict = {"verdict": why, "model": served, "cost_usd_list_price": round(spend, 2), "seconds": int(time.time() - t0),
                   "builds": [{"n": b["n"], "ok": b["ok"]} for b in s.builds], "trials": s.trials}
        if s.result and s.result[0] == "give_up": verdict["reason"] = s.result[1]
        (s.work / "verdict.json").write_text(json.dumps(verdict, indent=2))
        say(f"recipe agent: {why}  ({len(s.builds)} builds, {len(s.trials)} harness runs, ~${spend:.2f} at list price, {int(time.time() - t0)} s)")
        sys.exit(code)

    for turn in range(1, max_turns + 1):
        if spend >= max_usd: stop(1, f"stopped: spend reached the ${max_usd:.0f} cap (RECIPE_AGENT_MAX_USD)")
        if time.time() - t0 >= max_s: stop(1, f"stopped: {max_s} s elapsed (RECIPE_AGENT_MAX_SECONDS)")
        if label.startswith("bedrock/") and not any(k in model for k in TOP_LEVEL_CACHE):
            mark_cache(messages); caching = {"system": [{**system[0], "cache_control": {"type": "ephemeral"}}]}
        else: caching = {"system": system, "cache_control": {"type": "ephemeral"}}
        try:
            with client.messages.stream(model=model, max_tokens=64000, tools=TOOLS, messages=messages, **caching,
                                        thinking={"type": "adaptive", "display": "summarized"}, output_config={"effort": effort}) as stream:
                r = stream.get_final_message()
        except anthropic.APIStatusError as e: stop(1, f"model API error {e.status_code} from {model}: {e.message}")
        except anthropic.APIConnectionError as e: stop(1, f"model API unreachable ({model}): {e}")
        spend += cost(model, r.usage)
        log.write(json.dumps({"turn": turn, "model": model, "stop_reason": r.stop_reason, "usage": r.usage.to_dict(),
                              "content": [b.to_dict() for b in r.content]}) + "\n"); log.flush()
        if r.stop_reason == "refusal":
            why = getattr(r.stop_details, "category", None) if r.stop_details else None
            if label == fallback: stop(1, f"{model} declined the request ({why}) and so did the fallback")
            say(f"   {model} declined the request ({why}); the rest of the session runs on {fallback}")
            (client, model), label = connect(fallback), fallback; served.append(model)
            continue   # the same request again, on the fallback; the refused reply is not part of the conversation
        messages.append({"role": "assistant", "content": r.content})
        narrate(r.content)
        uses = [b for b in r.content if b.type == "tool_use"]
        if not uses:
            nudges += 1
            if nudges > 3: stop(1, "stopped: the model ended its turn without submitting, four times")
            messages.append({"role": "user", "content": "Nothing has been submitted. Continue until you call submit with a proven "
                                                        "build, or give_up with what you found."})
            continue
        results = []
        for u in uses:
            say(f"→ {brief(u.name, u.input)}")
            if r.stop_reason == "max_tokens":
                out, err = "Your reply reached the output limit before this call was complete; issue it again.", True
            else:
                try: out, err = s.call(u.name, u.input), False
                except ToolError as e: out, err = str(e), True
                except (KeyError, TypeError, ValueError) as e: out, err = f"bad input: {type(e).__name__}: {e}", True
            if err: say(f"   ✗ {out[:300]}")
            results.append({"type": "tool_result", "tool_use_id": u.id, "content": out, **({"is_error": True} if err else {})})
            if s.result: break
        log.write(json.dumps({"turn": turn, "results": results}) + "\n"); log.flush()
        if s.result: break
        messages.append({"role": "user", "content": results})
    else:
        stop(1, f"stopped: {max_turns} turns without a proven recipe (RECIPE_AGENT_MAX_TURNS)")

    if s.result[0] == "give_up":
        say(f"recipe agent gave up: {s.result[1]}")
        stop(3, "cannot run here")
    _, final, b, proof = s.result
    Path(a.out).write_text(json.dumps({"type": "result", "subtype": "success", "structured_output": final, "num_turns": turn,
                                       "total_cost_usd": round(spend, 4), "agent": {"model": served, "build": b["n"], "proof_trial": proof}}))
    stop(0, f"proven: build {b['n']}, trial {proof['n']} made {proof['calls']} model calls ({proof['answered']} answered)")


if __name__ == "__main__":
    main()
