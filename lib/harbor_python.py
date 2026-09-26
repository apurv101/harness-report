"""Launch the optional, pinned Harbor runtime without adding dependencies to the API."""
import os
from pathlib import Path
import shlex
import shutil
import sys


def interpreter():
    if os.environ.get("HR_HARBOR_PYTHON"):
        return os.environ["HR_HARBOR_PYTHON"]
    local = Path(__file__).resolve().parents[1] / ".venv-harbor/bin/python"
    if local.exists():
        return str(local)
    executable = shutil.which("harbor")
    if executable:
        first = Path(executable).read_text().splitlines()[0]
        if first.startswith("#!"):
            parts = shlex.split(first[2:])
            if len(parts) == 1 and Path(parts[0]).is_file():
                return parts[0]
    return sys.executable


if __name__ == "__main__":
    python = interpreter()
    os.execv(python, [python, str(Path(__file__).with_name("harbor_backend.py")), *sys.argv[1:]])
