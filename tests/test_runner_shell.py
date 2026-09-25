"""Exercise startup and task selection on the host shell (GNU tools in CI)."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RunnerShellTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = Path(self.tmp.name)
        shutil.copy2(ROOT / "run.sh", self.app)
        shutil.copytree(ROOT / "lib", self.app / "lib", ignore=shutil.ignore_patterns("__pycache__"))
        (self.app / ".env").write_text("MODEL=openai/test\n")
        self.bin = self.app / "bin"
        self.bin.mkdir()
        for name, body in (("docker", "echo amd64"), ("claude", "exit 0"), ("git", "echo fixture-clone-reached >&2; exit 1")):
            path = self.bin / name
            path.write_text("#!/bin/sh\n" + body + "\n")
            path.chmod(0o755)
        self.env = {**os.environ, "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
                    "HR_DATA_DIR": str(self.app), "HR_EVENTS": "", "MODEL": "openai/test", "ROUTES": ""}
        self.taskset = self.app / "Mixed_Task-Set"
        task = self.taskset / "example"
        (task / "environment").mkdir(parents=True)
        (task / "task.toml").write_text('version = "1.0"\n')
        (task / "environment/Dockerfile").write_text("FROM python:3.12-slim\n")

    def shell(self, code, *args):
        return subprocess.run(["bash", "-euo", "pipefail", "-c", code, "test", str(self.app), *map(str, args)],
                              env=self.env, text=True, capture_output=True, timeout=20)

    def test_github_name_reaches_clone_on_linux_and_macos(self):
        result = self.shell('bash "$1/run.sh" https://github.com/SWE-agent/mini-swe-agent "fixture task"')
        self.assertIn("swe-agent-mini-swe-agent", result.stdout)
        self.assertIn("fixture-clone-reached", result.stderr)
        self.assertNotIn("range-endpoints", result.stderr)

    def test_task_selection_normalizes_name(self):
        result = self.shell('''HERE="$1"; HARBOR_TASKS="$1"; TASKSET="$2"; T0=0
source "$HERE/lib/common.sh"; source "$HERE/lib/harbor.sh"
TASK_NAMES=example; TASKS=(); K=1; RUN_ID=fixture
task_image() { echo fixture-image; }
select_tasks
printf 'selected=%s\n' "$TS_NAME"
''', self.taskset)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("selected=mixed_task-set", result.stdout)

    def test_oracle_normalizes_name_before_checking_solution(self):
        result = self.shell('bash "$1/run.sh" oracle "$2" example', self.taskset)
        self.assertIn("oracle mixed_task-set/example", result.stdout)
        self.assertIn("no solution/solve.sh", result.stdout)
        self.assertNotIn("range-endpoints", result.stderr)


if __name__ == "__main__": unittest.main()
