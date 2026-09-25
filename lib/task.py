#!/usr/bin/env python3
"""task.py — read a Harbor task.toml.  Called by task_meta() in lib/harbor.sh, and imported by lib/tasks.py.

    task.py <task-dir>

Prints one tab-separated line, the fields the runner needs from a task:

    difficulty  category  agent_timeout  verifier_timeout  cpus  memory  docker_image  compose

`compose` is the string "compose" when the task brings a docker-compose file, which this runner cannot run.
"""
import sys, tomllib, os

COMPOSE = ("docker-compose.yaml", "docker-compose.yml", "compose.yaml")


def meta(d):
    """Everything this repo reads out of one task folder's task.toml, as a dict."""
    t = tomllib.load(open(f"{d}/task.toml", "rb"))
    env = t.get("environment", {}); m = t.get("metadata", {})
    mem = env.get("memory_mb"); mem = f"{int(mem)}m" if mem else str(env.get("memory", "")).lower()
    tags = m.get("tags") or []
    return {"difficulty": str(m.get("difficulty", "")), "category": str(m.get("category", "")),
            "tags": [str(x) for x in tags] if isinstance(tags, list) else [str(tags)],
            "language": str(m.get("language", "") or ""),
            "agent_timeout": int(t.get("agent", {}).get("timeout_sec", 1800)),
            "verifier_timeout": int(t.get("verifier", {}).get("timeout_sec", 1800)),
            "cpus": env.get("cpus", ""), "memory": mem, "docker_image": env.get("docker_image", ""),
            "compose": any(os.path.exists(f"{d}/environment/{f}") for f in COMPOSE)}


if __name__ == "__main__":
    x = meta(sys.argv[1])
    print("\t".join(str(v) for v in [x["difficulty"], x["category"], x["agent_timeout"], x["verifier_timeout"], x["cpus"],
                                      x["memory"], x["docker_image"], "compose" if x["compose"] else ""]))
