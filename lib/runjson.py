#!/usr/bin/env python3
"""runjson.py — build runs/<run-id>/run.json in three passes.

    runjson.py origin <out> <run> <name> <repo> <commit> <taskset> <tsd> <task> <model> <workdir> <cmd> <api>
                      <routes> <egress> <policy> <block-urls>
    runjson.py provenance <out> <platform> <host-platform> <docker-version> <task-image> <task-image-id>
                      <overlay-tag> <overlay-id> <recipe-hash> <commit> <seeded-from|reused> <changed-vs-previous>
                      <proxy-commit> <proxy-dirty> <proxy.py>
    runjson.py result <out> <rc> <seconds> <reward> <verifier-rc>

`origin` and `provenance` are written before the agent starts, so even a run that dies says where it came from and
exactly what ran.  `result` merges the outcome in afterwards and prints the run's one-line summary; it reads
calls.jsonl and egress.jsonl for the token, flag and egress totals.  Called by lib/execute.sh.
"""
import collections, hashlib, json, os, sys, time


def origin(args):
    """Where this run came from: harness, task, model and the interception settings."""
    out, run, name, repo, commit, taskset, tsd, task, model, workdir, cmd, api, routes, egress, pol, blocks = args
    rec = {"run": run, "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "finished": None, "kind": "harbor" if taskset else "prompt",
           "harness": {"name": name, "repo": "https://github.com/" + repo, "commit": commit, "api_style": api},
           "task": {"name": task, "taskset": taskset, "taskset_dir": tsd} if taskset else {"name": None, "taskset": None},
           "prompt": None if taskset else open(f"{out}/task.txt").read().strip(),
           "model": model, "routes": routes or None,
           "interception": {"egress": egress, "policy": pol, "block_urls": [b for b in blocks.split("\n") if b]}, "workdir": workdir, "run_command": cmd}
    json.dump(rec, open(f"{out}/run.json", "w"), indent=2)


def provenance(args):
    """Exactly what ran, field by field, so a laptop run and an AWS run can be compared."""
    out, plat, host, dver, timg, timg_id, otag, otag_id, rh, commit, seeded, changed, pcommit, pdirty, proxy = args
    rec = json.load(open(f"{out}/run.json"))
    rec["provenance"] = {
        "platform": plat, "host_platform": host, "emulated": plat != host, "docker": dver,
        "task_image": {"tag": timg, "id": timg_id} if timg else None, "overlay_image": {"tag": otag, "id": otag_id},
        "recipe": {"sha256": rh, "commit": commit, "file": f"recipes/{rec['harness']['name']}@{commit}.json",
                   "analyzed_now": seeded != "reused", "seeded_from": None if seeded in ("reused", "none") else seeded,
                   "changed_vs_previous": changed == "1"},
        "proxy": {"commit": pcommit or None, "modified": pdirty == "1", "sha256": hashlib.sha256(open(proxy, "rb").read()).hexdigest()[:16]}}
    json.dump(rec, open(f"{out}/run.json", "w"), indent=2)


def result(args):
    """The outcome, merged into the origin written above, and the run's one-line summary on stdout."""
    out, rc, secs, reward, vrc = args
    def interception(out):
        """egress + policy totals for run.json, from egress.jsonl and the flags/rewrites in calls.jsonl."""
        eg = [json.loads(l) for l in open(f"{out}/egress.jsonl")] if os.path.exists(f"{out}/egress.jsonl") else []
        agent = [e for e in eg if e.get("phase") == "agent" and e.get("rule") != "self"]
        hosts = collections.Counter((e["host"], bool(e.get("allowed"))) for e in agent)
        flags = collections.Counter(f["rule"] for c in calls for f in c.get("flags") or [])
        return {"egress": {"connections": len(agent), "blocked": sum(1 for e in agent if not e.get("allowed")),
                           "tls_failed": sum(1 for e in agent if e.get("kind") == "tls"), "verify_phase": sum(1 for e in eg if e.get("phase") == "verify"),
                           "hosts": [{"host": h, "allowed": a, "n": n} for (h, a), n in sorted(hosts.items())]},
                "flags": dict(sorted(flags.items())), "rewrites": sum(len(c.get("rewrites") or []) for c in calls)}
    calls = [json.loads(l) for l in open(f"{out}/calls.jsonl")] if os.path.exists(f"{out}/calls.jsonl") else []
    rec = json.load(open(f"{out}/run.json"))
    rec.update({"finished": time.strftime("%Y-%m-%dT%H:%M:%S"), "rc": int(rc), "seconds": int(secs), "reward": json.loads(reward),
                "verifier_rc": int(vrc) if vrc else None, "calls": len(calls),
                "input_tokens": sum(c["usage"].get("input_tokens") or 0 for c in calls), "output_tokens": sum(c["usage"].get("output_tokens") or 0 for c in calls),
                "errors": sum(1 for c in calls if c.get("error")),
                **interception(out),
                "models": [{"requested": r, "served": s, "calls": n} for (r, s), n in
                           sorted(collections.Counter((c.get("model_requested"), c.get("model")) for c in calls).items(), key=str)],
                "files": sorted(os.listdir(out))})
    json.dump(rec, open(f"{out}/run.json", "w"), indent=2)
    print(f"rc={rc}  {secs}s  model calls={len(calls)} (in={rec['input_tokens']} out={rec['output_tokens']} tokens, {rec['errors']} errors)" + (f"  reward={reward}" if rec["kind"] == "harbor" else ""))
    e = rec["egress"]; print(f"egress: {e['connections']} connections, {e['blocked']} blocked" + (f", {e['tls_failed']} refused interception" if e["tls_failed"] else "")
          + (f"   flags: {rec['flags']}" if rec["flags"] else "") + (f"   rewrites: {rec['rewrites']}" if rec["rewrites"] else ""))
    if not calls: print("WARNING: no model calls reached the proxy (check stderr.log and the env in recipe.json)", file=sys.stderr)


if __name__ == "__main__":
    {"origin": origin, "provenance": provenance, "result": result}[sys.argv[1]](sys.argv[2:])
