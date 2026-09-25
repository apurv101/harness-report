"""Serialize fleet decisions in a short-lived Lambda; no continuously running scheduler.

One active owner needs one VM. Keep protected booting/executing workers alive until
their retirement callback; the worker service has a finite runtime even on failure.
SQS depth is not demand: ten queued jobs from one owner still need only one slot.
"""
import os
import time

import cloudqueue


def capacity(jobs, instances, maximum):
    owners = {job["user"].lower() for job in jobs}
    protected = sum(bool(i.get("ProtectedFromScaleIn")) for i in instances
                    if i["LifecycleState"] == "InService" or i["LifecycleState"].startswith("Pending"))
    return min(maximum, max(len(owners), protected))


def reconcile(asg, name, retire=None, enabled=True):
    groups = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[name])["AutoScalingGroups"]
    if not groups: return {"absent": True}
    group = groups[0]
    # Duplicate callbacks are harmless. Never allow this function to retire another fleet's VM.
    member = next((i for i in group["Instances"] if i["InstanceId"] == retire), None)
    if member and not member["LifecycleState"].startswith("Terminating"):
        asg.terminate_instance_in_auto_scaling_group(InstanceId=retire, ShouldDecrementDesiredCapacity=True)
        # Describe is eventually consistent: use the acknowledged mutation instead
        # of immediately reading a stale InService row and requesting a replacement.
        group["DesiredCapacity"] = max(0, group["DesiredCapacity"] - 1)
        group["Instances"] = [i for i in group["Instances"] if i["InstanceId"] != retire]
    jobs = cloudqueue.active() if enabled else []
    for job in jobs:
        if job["status"] == "running" and job.get("lease_until", 0) < time.time():
            cloudqueue.expire(job["id"])
    jobs = cloudqueue.active() if enabled else []
    desired = capacity(jobs, group["Instances"], group["MaxSize"])
    if desired != group["DesiredCapacity"]:
        asg.set_desired_capacity(AutoScalingGroupName=name, DesiredCapacity=desired, HonorCooldown=False)
    return {"desired": desired, "active_jobs": len(jobs), "retired": retire if member else None}


def handler(event, context):
    import boto3
    result = reconcile(boto3.client("autoscaling"), os.environ["HR_ASG_NAME"], (event or {}).get("retire"),
                       enabled=os.environ.get("HR_DISPATCH") == "1")
    print(result, flush=True)
    return result
