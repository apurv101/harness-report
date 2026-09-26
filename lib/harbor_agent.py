"""Harbor installed-agent bridge for an already-built Harness Report overlay."""
import json
from pathlib import Path
import shlex

from harbor.agents.installed.base import BaseInstalledAgent, NonZeroAgentExitCodeError


class RecipeAgent(BaseInstalledAgent):
    @staticmethod
    def name():
        return "harness-report"

    def __init__(self, *, bridge_file, **kwargs):
        super().__init__(**kwargs)
        self.bridge = json.loads(Path(bridge_file).read_text())

    async def install(self, environment):
        # The recipe was installed into the overlay by our ordinary build stage.
        await environment.upload_file(self.bridge["wrapper"], "/usr/local/bin/run-harness")
        result = await environment.exec("chmod +x /usr/local/bin/run-harness", user="root")
        if result.return_code:
            raise RuntimeError("could not install harness launcher")

    async def run(self, instruction, environment, context):
        prompt = self.logs_dir / "instruction.md"
        prompt.write_text(instruction)
        await environment.upload_file(prompt, "/tmp/hr-instruction.md")
        result = await environment.exec(
            "bash -lc " + shlex.quote("run-harness " + shlex.quote(self.bridge["workdir"]) + " /tmp/hr-instruction.md"),
            cwd=self.bridge["workdir"], env=self.bridge["env"],
        )
        Path(self.bridge["out"], "agent-exit.json").write_text(json.dumps({"rc": result.return_code}))
        if result.return_code:
            raise NonZeroAgentExitCodeError(f"Harness exited with status {result.return_code}")
