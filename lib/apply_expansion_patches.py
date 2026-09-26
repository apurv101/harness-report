#!/usr/bin/env python3
"""Apply the reviewed, checksum-guarded expansion fixes to a downloaded Harbor corpus.

Usage: python3 lib/apply_expansion_patches.py [CORPUS_ROOT] [--check]
"""
import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path


def apply(root, check=False):
    ledger = Path(__file__).resolve().parents[1] / 'catalog/expansion-patches.json'
    groups = defaultdict(list)
    for record in json.loads(ledger.read_text()):
        groups[record['path']].append(record)
    pending = {}
    for relative, records in groups.items():
        path = root / relative
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest == records[-1]['after_sha256']:
            continue
        if check:
            raise ValueError(f'{relative}: expected final patched checksum')
        for record in records:
            if digest != record['before_sha256']:
                continue
            old, new = record['replace']['old'], record['replace']['new']
            if content.decode().count(old) != 1:
                raise ValueError(f'{relative}: patch context is ambiguous')
            content = content.decode().replace(old, new).encode()
            digest = hashlib.sha256(content).hexdigest()
            if digest != record['after_sha256']:
                raise ValueError(f'{relative}: unexpected patch result')
        if digest != records[-1]['after_sha256']:
            raise ValueError(f'{relative}: unknown content; refusing to overwrite')
        pending[path] = content
    # Validate every file before changing any of them.
    for path, content in pending.items():
        path.write_bytes(content)
    print(f'{len(groups)} adapter files verified; {len(pending)} updated')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', nargs='?', type=Path, default=Path(os.environ.get('HARBOR_TASKS', Path.home() / 'Desktop/harbor-tasks')))
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    apply(args.root, args.check)
