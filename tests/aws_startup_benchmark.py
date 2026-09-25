#!/usr/bin/env python3
"""Opt-in, billable startup probes using operator; isolated resources are cleaned up.

Compare CodeBuild on-demand (two builds) with a supplied prepared EC2 AMI (one
cold boot, two stopped resumes). Runs a tiny Python test in Docker, never an agent
or a model. Measures provider request -> Docker ready and -> test completed; this
does not include the app's queue dispatch or repository-specific build/analysis.
"""
import argparse
import base64
import json
from pathlib import Path
import re
import subprocess
import time
import uuid

REGION = "us-west-2"
PROFILE = "operator"


def aws(service, operation, **request):
    result = subprocess.run(["aws", "--profile", PROFILE, "--region", REGION, service, operation,
        "--cli-input-json", json.dumps(request), "--output", "json"], capture_output=True, text=True, timeout=60)
    if result.returncode: raise RuntimeError(f"{service} {operation}: {result.stderr}")
    return json.loads(result.stdout) if result.stdout.strip() else {}


def wait_for(check, seconds=600):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = check()
        if result: return result
        time.sleep(5)
    raise TimeoutError("startup benchmark deadline exceeded")


def marks(text, started):
    found = {}
    for label, timestamp in re.findall(r"HR_BENCH_(DOCKER_READY|TOOLS_READY|TEST_DONE)=([0-9.]+)", text):
        if float(timestamp) >= started:
            found[label.lower() + "_seconds"] = round(float(timestamp) - started, 3)
    return found


COMMANDS = [
    "docker info >/dev/null",
    "echo HR_BENCH_DOCKER_READY=$(date +%s.%N)",
    "docker run --rm --network none python:3.12-slim python3 -c 'assert sum(range(10000)) == 49995000'",
    "echo HR_BENCH_TEST_DONE=$(date +%s.%N)",
]


def codebuild(name):
    role = project = False
    builds = []
    group = "/aws/codebuild/" + name
    account = aws("sts", "get-caller-identity")["Account"]
    try:
        response = aws("iam", "create-role", RoleName=name, AssumeRolePolicyDocument=json.dumps({
            "Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "sts:AssumeRole",
            "Principal": {"Service": "codebuild.amazonaws.com"}}]}))
        role = True
        aws("iam", "put-role-policy", RoleName=name, PolicyName="probe-logs", PolicyDocument=json.dumps({
            "Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": [
            "logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
            "Resource": f"arn:aws:logs:{REGION}:{account}:log-group:{group}*"}]}))
        for attempt in range(12):
            try:
                aws("codebuild", "create-project", name=name, source={"type": "NO_SOURCE", "buildspec": json.dumps({
                    "version": 0.2, "phases": {"build": {"commands": COMMANDS}}})},
                    artifacts={"type": "NO_ARTIFACTS"}, environment={"type": "LINUX_CONTAINER",
                    "image": "aws/codebuild/standard:7.0", "computeType": "BUILD_GENERAL1_LARGE", "privilegedMode": True},
                    serviceRole=response["Role"]["Arn"], timeoutInMinutes=10, queuedTimeoutInMinutes=10,
                    concurrentBuildLimit=1, cache={"type": "LOCAL", "modes": ["LOCAL_DOCKER_LAYER_CACHE"]},
                    logsConfig={"cloudWatchLogs": {"status": "ENABLED", "groupName": group}})
                project = True
                break
            except RuntimeError:
                if attempt == 11: raise
                time.sleep(5)
        results = []
        for n in range(2):
            started = time.time()
            build_id = aws("codebuild", "start-build", projectName=name)["build"]["id"]
            builds.append(build_id)
            print(f"CodeBuild probe {n + 1}: {build_id}", flush=True)
            def done():
                build = aws("codebuild", "batch-get-builds", ids=[build_id])["builds"][0]
                return build if build.get("buildComplete") else None
            build = wait_for(done, 900)
            logs = aws("logs", "get-log-events", logGroupName=group,
                       logStreamName=build["logs"]["streamName"], startFromHead=True)["events"]
            result = {"platform": "codebuild", "attempt": n + 1, "status": build["buildStatus"],
                      "phases": [{"type": p["phaseType"], "seconds": p.get("durationInSeconds")} for p in build["phases"]],
                      **marks("\n".join(e["message"] for e in logs), started)}
            results.append(result)
            print(json.dumps(result), flush=True)
            if build["buildStatus"] != "SUCCEEDED":
                raise RuntimeError("CodeBuild probe failed: " + "\n".join(e["message"] for e in logs)[-3000:])
        return results
    finally:
        for build_id in builds:
            build = aws("codebuild", "batch-get-builds", ids=[build_id])["builds"][0]
            if not build.get("buildComplete"): aws("codebuild", "stop-build", id=build_id)
        if project: aws("codebuild", "delete-project", name=name)
        if role:
            aws("iam", "delete-role-policy", RoleName=name, PolicyName="probe-logs")
            aws("iam", "delete-role", RoleName=name)
        try: aws("logs", "delete-log-group", logGroupName=group)
        except RuntimeError as e:
            if "ResourceNotFoundException" not in str(e): raise
        print(f"Removed CodeBuild probe resources: {name}", flush=True)


def ec2(name, ami):
    group = iid = None
    try:
        wait_for(lambda: aws("ec2", "describe-images", ImageIds=[ami])["Images"][0]["State"] == "available", 900)
        vpc = aws("ec2", "describe-vpcs", Filters=[{"Name": "is-default", "Values": ["true"]}])["Vpcs"][0]["VpcId"]
        subnet = aws("ec2", "describe-subnets", Filters=[{"Name": "vpc-id", "Values": [vpc]}])["Subnets"][0]["SubnetId"]
        group = aws("ec2", "create-security-group", GroupName=name, Description="Isolated startup probe; no ingress", VpcId=vpc)["GroupId"]
        script = "\n".join(["#!/bin/bash", "set -euo pipefail", "cat > /usr/local/bin/hr-startup-probe <<'PROBE'",
            "#!/bin/bash", "set -euo pipefail", *COMMANDS, "PROBE", "chmod +x /usr/local/bin/hr-startup-probe",
            "cat > /etc/systemd/system/hr-startup-probe.service <<'UNIT'", "[Unit]", "After=docker.service",
            "Requires=docker.service", "[Service]", "Type=oneshot", "StandardOutput=journal+console",
            "StandardError=journal+console", "ExecStart=/usr/local/bin/hr-startup-probe", "[Install]",
            "WantedBy=multi-user.target", "UNIT", "systemctl daemon-reload",
            "systemctl enable --now hr-startup-probe"])
        started = time.time()
        instance = aws("ec2", "run-instances", ImageId=ami, InstanceType="c6i.2xlarge", MinCount=1, MaxCount=1,
            NetworkInterfaces=[{"DeviceIndex": 0, "SubnetId": subnet, "Groups": [group], "AssociatePublicIpAddress": True}],
            UserData=script,  # AWS CLI encodes this field, including with --cli-input-json.
            MetadataOptions={"HttpTokens": "required", "HttpPutResponseHopLimit": 1},
            TagSpecifications=[{"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": name},
                {"Key": "Project", "Value": "harness-report"}, {"Key": "Purpose", "Value": "startup-benchmark"}]}])["Instances"][0]
        iid = instance["InstanceId"]
        print(f"EC2 probe: {iid} from {ami}", flush=True)
        results = []
        for n in range(3):
            if n:
                aws("ec2", "stop-instances", InstanceIds=[iid])
                def stopped():
                    return aws("ec2", "describe-instances", InstanceIds=[iid])["Reservations"][0]["Instances"][0]["State"]["Name"] == "stopped"
                wait_for(stopped, 300)
                started = time.time()
                aws("ec2", "start-instances", InstanceIds=[iid])
            def done():
                output = aws("ec2", "get-console-output", InstanceId=iid, Latest=True).get("Output", "")
                if "HR_BENCH_" not in output:
                    try: output = base64.b64decode(output).decode(errors="replace")
                    except ValueError: pass
                found = marks(output, started)
                return found if "test_done_seconds" in found else None
            result = {"platform": "ec2-prepared-cold" if n == 0 else "ec2-stopped-resume", "attempt": n + 1,
                      **wait_for(done)}
            results.append(result)
            print(json.dumps(result), flush=True)
        return results
    finally:
        if iid:
            aws("ec2", "terminate-instances", InstanceIds=[iid])
            def terminated():
                return aws("ec2", "describe-instances", InstanceIds=[iid])["Reservations"][0]["Instances"][0]["State"]["Name"] == "terminated"
            wait_for(terminated, 300)
        if group: aws("ec2", "delete-security-group", GroupId=group)
        print(f"Removed EC2 probe resources: {name}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ami")
    parser.add_argument("--codebuild", action="store_true")
    parser.add_argument("--tools", action="store_true", help="include the worker's boto3 and Claude CLI prerequisites on CodeBuild")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.tools:
        COMMANDS[2:2] = ["python3 -c 'import boto3' || pip3 install -q boto3",
            "curl -fsSL https://claude.ai/install.sh -o /tmp/hr-install.sh",
            "CLAUDE_INSTALL_ALLOW_SUDO=1 bash /tmp/hr-install.sh",
            "/root/.local/bin/claude --version", "echo HR_BENCH_TOOLS_READY=$(date +%s.%N)"]
    if not args.ami and not args.codebuild: parser.error("choose --ami or --codebuild")
    name = "hr-startup-" + uuid.uuid4().hex[:12]
    results = []
    try:
        if args.codebuild: results += codebuild(name)
        if args.ami: results += ec2(name, args.ami)
    finally:
        Path(args.output).write_text(json.dumps({"region": REGION, "results": results}, indent=2) + "\n")
