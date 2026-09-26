"""The recipe agent's loop and gate, with a scripted model and a fake trial.sh: no API, no Docker."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import recipe_agent as ra  # noqa: E402

RECIPE = {"base_image": "python:3.12-slim", "dockerfile": "ARG BASE=python:3.12-slim\nFROM ${BASE}\nRUN true\n",
          "run_command": 'agent -t "$TASK"', "check_command": "agent --help", "api_style": "openai",
          "env": [{"name": "OPENAI_BASE_URL", "value": "$PROXY_URL/v1"}]}


def block(**kw):
    return types.SimpleNamespace(**kw, to_dict=lambda: kw)


def reply(*tool_calls):
    usage = types.SimpleNamespace(input_tokens=1000, output_tokens=100, cache_creation_input_tokens=0, cache_read_input_tokens=0,
                                  to_dict=lambda: {})
    content = [block(type="tool_use", id=f"t{i}", name=n, input=inp) for i, (n, inp) in enumerate(tool_calls)]
    return types.SimpleNamespace(content=content, usage=usage, stop_reason="tool_use", stop_details=None)


class ScriptedModel:
    """messages.stream(...) returns the next scripted reply and keeps what it was sent."""
    def __init__(self, replies): self.replies, self.sent = list(replies), []
    @property
    def messages(self): return self
    def stream(self, **kw):
        self.sent.append({**kw, "messages": list(kw["messages"])})   # the loop appends to one list; keep it as sent
        return _Stream(self.replies.pop(0))


class _Stream:
    def __init__(self, r): self.r = r
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def get_final_message(self): return self.r


def fake_trial(calls):
    """trial.sh stand-in: builds succeed, and a run leaves `calls` model calls in calls.jsonl."""
    def trial(cmd, *args, timeout):
        if cmd == "build": return 0, "overlay built\ncheck passed"
        if cmd == "run":
            out = Path(args[4])
            (out / "calls.jsonl").write_text("".join(json.dumps({"n": i + 1, "route": "openai", "path": "/v1/chat/completions",
                                                                  "model_requested": "gpt-4o", "error": None}) + "\n" for i in range(calls)))
            (out / "changes.txt").write_text("C /work\nA /work/hello.txt\nC /opt\nA /opt/x/__pycache__\n")
            return 0, "rc=0 seconds=9"
        return 0, ""
    return trial


class RecipeAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.tmp)]))
        (self.tmp / "src").mkdir(); (self.tmp / "src/README.md").write_text("agent\n")
        self.args = ["--src", str(self.tmp / "src"), "--repo-url", "https://github.com/o/r", "--commit", "abc", "--name", "o-r",
                     "--work", str(self.tmp / "work"), "--out", str(self.tmp / "analyze.raw.json")]

    def run_agent(self, model, calls):
        fake_sdk = types.SimpleNamespace(APIStatusError=RuntimeError, APIConnectionError=ConnectionError)
        with mock.patch.object(ra, "connect", return_value=(model, "claude-test")), mock.patch.object(ra, "trial", fake_trial(calls)), \
             mock.patch.dict(sys.modules, {"anthropic": fake_sdk}), mock.patch.object(sys, "argv", ["recipe_agent.py", *self.args]):
            with self.assertRaises(SystemExit) as done: ra.main()
        return done.exception.code

    def test_submit_is_refused_until_a_run_reaches_the_model(self):
        model = ScriptedModel([reply(("build", RECIPE)), reply(("submit", {"summary": "s"})),
                               reply(("run_harness", {"target": "base"})), reply(("submit", {"summary": "s", "notes": "n"}))])
        self.assertEqual(self.run_agent(model, calls=2), 0)
        refused = model.sent[2]["messages"][-1]["content"][0]
        self.assertTrue(refused["is_error"]); self.assertIn("has reached the model", refused["content"])
        run = model.sent[3]["messages"][-1]["content"][0]["content"]
        self.assertIn("2 reached the proxy, 2 answered", run)
        self.assertIn("A /work/hello.txt", run); self.assertNotIn("__pycache__", run); self.assertNotIn("C /work\n", run)
        raw = json.loads((self.tmp / "analyze.raw.json").read_text())
        self.assertEqual(raw["structured_output"]["run_command"], RECIPE["run_command"])
        self.assertEqual(raw["structured_output"]["notes"], "n")
        # the pipeline reads it exactly as it reads claude -p's answer
        out = subprocess.run([sys.executable, str(ROOT / "lib/recipe.py"), "save", str(self.tmp / "analyze.raw.json"),
                              str(self.tmp / "recipe.json"), str(self.tmp / "Dockerfile")], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_a_run_with_no_model_calls_does_not_prove_a_build(self):
        model = ScriptedModel([reply(("build", RECIPE)), reply(("run_harness", {"target": "base"})),
                               reply(("submit", {"summary": "s"})), reply(("give_up", {"reason": "it never calls a model"}))])
        self.assertEqual(self.run_agent(model, calls=0), 3)
        self.assertTrue(model.sent[3]["messages"][-1]["content"][0]["is_error"])
        verdict = json.loads((self.tmp / "work/verdict.json").read_text())
        self.assertEqual(verdict["reason"], "it never calls a model")
        self.assertFalse((self.tmp / "analyze.raw.json").exists())

    def test_reads_stay_inside_their_root(self):
        s = ra.Session(types.SimpleNamespace(src=str(self.tmp / "src"), work=str(self.tmp / "work"), task_dir=None, task_image=None,
                                             name="o-r", commit="abc"))
        self.assertIn("agent", s.call("read_file", {"path": "README.md"}))
        with self.assertRaises(ra.ToolError): s.call("read_file", {"path": "../src/../../etc/passwd"})
        with self.assertRaises(ra.ToolError): s.call("build", {**RECIPE, "dockerfile": "FROM python:3.12\n"})


if __name__ == "__main__":
    unittest.main()
