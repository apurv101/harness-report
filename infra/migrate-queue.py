#!/usr/bin/env python3
"""Move pending standard-queue messages to FIFO without executing evaluations.

Stop legacy consumers before running. The original message is deleted only after
FIFO accepts its replacement; terminal jobs are acknowledged without rerunning.
Use AWS_PROFILE=operator. This never creates model calls or stores clone tokens.
"""
import argparse
import os
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[1] / "lib")]
os.environ.update(HR_DDB="", HR_DDB_ENDPOINT="", HR_EVALS="queue")
import cloudqueue, leases, store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--max-messages", type=int, default=100)
    args = parser.parse_args()
    if args.source == args.target or not args.target.endswith(".fifo"):
        parser.error("source and target must differ; target must be FIFO")
    migrated = dropped = 0
    for _ in range(args.max_messages):
        os.environ["HR_QUEUE_URL"] = args.source
        lease = leases.receive(wait=1, visibility=60)
        if not lease: break
        eid = (lease.get("body") or {}).get("eval")
        ev = cloudqueue.get(eid) if eid else None
        old = store.eval_record(eid) if eid else None
        ev = ev or old
        if not ev: raise RuntimeError(f"message {lease['id']} has no evaluation record; left on source queue")
        if ev["status"] == "running": raise RuntimeError(f"{eid} is still running; stop and settle its legacy worker first")
        if ev["status"] == "queued":
            if not ev.get("user"): raise RuntimeError(f"{eid} has no owner; left on source queue for manual review")
            if not cloudqueue.get(eid):
                ev = cloudqueue.enqueue({**ev, "installation": lease["body"].get("installation")}, daily_cap=0)
            else:
                ev = cloudqueue.update(eid, {})  # Backfill the active scheduling index on reruns.
            os.environ["HR_QUEUE_URL"] = args.target
            leases.send({"eval":eid, "user":ev["user"]})
            migrated += 1
        else: dropped += 1
        os.environ["HR_QUEUE_URL"] = args.source
        leases.delete(lease["receipt"])
    print(f"Migrated {migrated} queued jobs; acknowledged {dropped} already finished jobs.")


if __name__ == "__main__": main()
