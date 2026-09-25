"""Emit safely quoted shell defaults. Exported variables take precedence over .env."""
import os
import re
import shlex
import sys

for raw in open(sys.argv[1], encoding="utf-8"):
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line: continue
    key, value = line.split("=", 1)
    key = key.strip()
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) and key not in os.environ:
        print(f"export {key}={shlex.quote(value.strip().strip(chr(34) + chr(39)))}")
