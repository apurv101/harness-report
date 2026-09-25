#!/usr/bin/env python3
"""Gate queue consumption until InService, including stopped warm-pool resumes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

import boto3
from botocore.exceptions import ClientError

READY = Path("/run/hr-worker-ready")


def instance_id():
    request = urllib.request.Request("http://169.254.169.254/latest/api/token", method="PUT",
                                     headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"})
    with urllib.request.urlopen(request, timeout=5) as response: token = response.read().decode()
    request = urllib.request.Request("http://169.254.169.254/latest/meta-data/instance-id",
                                     headers={"X-aws-ec2-metadata-token": token})
    with urllib.request.urlopen(request, timeout=5) as response: return response.read().decode()


def ready():
    asg, iid = boto3.client("autoscaling"), instance_id()
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        rows = asg.describe_auto_scaling_instances(InstanceIds=[iid])["AutoScalingInstances"]
        if not rows: raise RuntimeError("instance does not belong to the worker fleet")
        row = rows[0]
        if row["AutoScalingGroupName"] != os.environ["HR_ASG_NAME"]: raise RuntimeError("unexpected fleet")
        state = row["LifecycleState"]
        if state == "InService":
            print(f"worker ready at {time.time():.3f}: {iid}", flush=True)
            READY.write_text(iid)
            # Refresh the private-clone key after a long wait in the stopped pool.
            try:
                value = boto3.client("ssm").get_parameter(Name=os.environ["HR_SECRET_PREFIX"] + "GITHUB_APP_KEY",
                                                          WithDecryption=True)["Parameter"]["Value"]
            except ClientError as e:
                if e.response["Error"]["Code"] != "ParameterNotFound": raise
            else:
                if value and value != "unset":
                    with open(os.open(os.environ["GITHUB_APP_KEY"], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
                        f.write(value)
            subprocess.run(["iptables", "-I", "DOCKER-USER", "-d", "169.254.169.254/32", "-j", "REJECT"], check=True)
            return
        if state.endswith(":Wait"):
            print(f"worker initialized at {time.time():.3f}: {iid} {state}", flush=True)
            try:
                asg.complete_lifecycle_action(AutoScalingGroupName=os.environ["HR_ASG_NAME"],
                    LifecycleHookName="worker-ready", InstanceId=iid, LifecycleActionResult="CONTINUE")
            except ClientError as e:
                # Describe can briefly return the previous state after a completed hook.
                if e.response["Error"]["Code"] != "ValidationError" or "No active Lifecycle Action" not in str(e): raise
        # Warmed:Pending -> Warmed:Stopped never reaches the queue. The OS stops us;
        # systemd reruns this gate on resume. Only unused machines enter that pool.
        time.sleep(2)
    raise RuntimeError("worker did not enter service before its readiness deadline")


def retire():
    if not READY.exists(): return  # Normal warm-pool stop, no job has been accepted.
    iid = READY.read_text().strip()
    for attempt in range(5):
        try:
            result = boto3.client("lambda").invoke(FunctionName=os.environ["HR_SCALER_FUNCTION"],
                InvocationType="RequestResponse", Payload=json.dumps({"retire": iid}).encode())
            if result.get("FunctionError"): raise RuntimeError("capacity controller failed to retire worker")
            return
        except Exception:
            if attempt == 4: raise
            time.sleep(2 ** attempt)


if __name__ == "__main__":
    if sys.argv[1] == "ready": ready()
    else:
        try: retire()
        finally:
            # If the callback was unavailable, this is a bounded fallback. The
            # periodic controller subsequently corrects the replacement capacity.
            if READY.exists(): subprocess.run(["shutdown", "-h", "now"], check=False)
