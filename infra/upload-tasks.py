#!/usr/bin/env python3
"""Upload Harbor tasksets for EC2 workers. Explicit tasksets avoid uploading the entire corpus.

AWS_PROFILE=operator python3 infra/upload-tasks.py --bucket BUCKET --root ~/Desktop/harbor-tasks aider_polyglot quixbugs
"""
import argparse
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--all", action="store_true", help="upload every taskset under the corpus root")
    parser.add_argument("tasksets", nargs="*")
    args = parser.parse_args()
    if args.all:
        names = set()
        for base in (args.root / "datasets", args.root / "hub-datasets", args.root):
            if base.is_dir():
                names.update(p.name for p in base.iterdir() if p.is_dir() and next(p.glob("*/task.toml"), None))
        args.tasksets = sorted(names)
    if not args.tasksets: parser.error("choose tasksets or --all")
    for name in args.tasksets:
        if not name or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for c in name):
            parser.error("taskset names must be simple directory names")
        source = next((p for p in (args.root / "datasets" / name, args.root / "hub-datasets" / name, args.root / name)
                       if p.is_dir()), None)
        if not source: parser.error(f"no taskset {name} under {args.root}")
        subprocess.run(["aws", "s3", "sync", str(source), f"s3://{args.bucket}/tasks/{name}/", "--only-show-errors"], check=True)
        print(f"Uploaded {name}")


if __name__ == "__main__": main()
