#!/usr/bin/env python3
"""events.py — append one JSON event to the file the site is tailing.  Called by emit() in lib/common.sh.

    events.py <events.jsonl> <key> <value> [<key> <value> ...]

A value that reads as a number, null, true or false is stored as that JSON type; anything else stays a string.
Every event carries a "ts".  Nothing here is fatal: emit() swallows a failure.
"""
import json, re, sys, time
d = {"ts": round(time.time(), 3)}
for k, v in zip(sys.argv[2::2], sys.argv[3::2]):
    d[k] = json.loads(v) if re.fullmatch(r"-?\d+(\.\d+)?|null|true|false", v) else v
with open(sys.argv[1], "a") as f: f.write(json.dumps(d) + "\n")
