#!/usr/bin/env python3
"""task.py — read a Harbor task.toml.  Called by task_meta() in lib/harbor.sh.

    task.py <task-dir>

Prints one tab-separated line, the fields the runner needs from a task:

    difficulty  category  agent_timeout  verifier_timeout  cpus  memory  docker_image  compose

`compose` is the string "compose" when the task brings a docker-compose file, which this runner cannot run.
"""
import sys, tomllib, os
d = sys.argv[1]; t = tomllib.load(open(f"{d}/task.toml", "rb"))
env = t.get("environment", {}); m = t.get("metadata", {})
mem = env.get("memory_mb"); mem = f"{int(mem)}m" if mem else str(env.get("memory", "")).lower()
compose = "compose" if any(os.path.exists(f"{d}/environment/{f}") for f in ("docker-compose.yaml", "docker-compose.yml", "compose.yaml")) else ""
print("\t".join(str(x) for x in [m.get("difficulty", ""), m.get("category", ""), int(t.get("agent", {}).get("timeout_sec", 1800)),
      int(t.get("verifier", {}).get("timeout_sec", 1800)), env.get("cpus", ""), mem, env.get("docker_image", ""), compose]))
