#!/bin/bash
# First boot only. A stopped worker resumes through systemd, with no reinstall.
set -euo pipefail
export AWS_DEFAULT_REGION='${region}' AWS_REGION='${region}'
if [ ! -f /etc/hr-image-ready ]; then
  ${install_script}
fi
mkdir -p /opt/harness-report /var/lib/hr/data /var/lib/hr/tasks
aws s3 cp 's3://${assets_bucket}/${release_key}' /tmp/runner.zip --only-show-errors
unzip -q /tmp/runner.zip -d /opt/harness-report
chmod +x /opt/harness-report/run.sh /opt/harness-report/hr-agentd
rm /tmp/runner.zip
# Older prepared images predate the optional Compose backend.
if ! /opt/hr-venv/bin/python /opt/harness-report/lib/harbor_backend.py check >/dev/null 2>&1; then
  /opt/hr-venv/bin/pip install --quiet -r /opt/harness-report/requirements-harbor.txt
fi
# Older prepared images predate the recipe agent's SDK.
if ! /opt/hr-venv/bin/python -c 'import anthropic' >/dev/null 2>&1; then
  /opt/hr-venv/bin/pip install --quiet -r /opt/harness-report/requirements-agent.txt
fi
if ! docker compose version >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y docker-compose-plugin
fi
cat > /opt/harness-report/.env <<'ENVFILE'
MODEL=${model}
ANALYZER_MODEL=${analyzer_model}
CLAUDE_CODE_USE_BEDROCK=1
ANALYZER=${analyzer}
RECIPE_AGENT_MODEL=${agent_model}
RECIPE_AGENT_FALLBACK=bedrock/${analyzer_model}
RECIPE_AGENT_MAX_SECONDS=2700
ENVFILE
cat > /etc/harness-report.env <<'ENVFILE'
PATH=/opt/hr-venv/bin:/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
AWS_REGION=${region}
AWS_DEFAULT_REGION=${region}
HR_RUNNER_EC2=1
HR_EVALS=on
HR_ISOLATED_RUN=1
HR_QUEUE_URL=${queue_url}
HR_TABLE=${table}
HR_RUNS_BUCKET=${runs_bucket}
HR_RECIPES_BUCKET=${recipes_bucket}
HR_TASKS_BUCKET=${assets_bucket}
HR_MODEL_ROLE_ARN=${model_role}
HR_ASG_NAME=${asg_name}
HR_SCALER_FUNCTION=${scaler_function}
HR_SECRET_PREFIX=${secret_prefix}
HR_MAX_JOB_SECONDS=${max_seconds}
HR_DATA_DIR=/var/lib/hr/data
HR_AGENT_PYTHON=/opt/hr-venv/bin/python
HARBOR_TASKS=/var/lib/hr/tasks
HR_PLATFORM=linux/amd64
GITHUB_APP_ID=${github_app_id}
GITHUB_APP_KEY=/opt/harness-report/github-app.pem
ENVFILE
# Pre-build the proxy before this unused machine is stopped, using the same
# Dockerfile as lib/proxy.sh so evaluation builds can reuse all its layers.
mkdir -p /tmp/hr-proxy
cp /opt/harness-report/proxy.py /opt/harness-report/policy.py /tmp/hr-proxy/
cat > /tmp/hr-proxy/Dockerfile <<'DOCKERFILE'
FROM python:3.12-slim
RUN pip install -q --root-user-action=ignore boto3 cryptography
COPY proxy.py policy.py /
CMD ["python3","-u","/proxy.py"]
DOCKERFILE
docker build -q -t hr-proxy:prepared /tmp/hr-proxy
rm -rf /tmp/hr-proxy
# Touch runtime files while preparing standby, before a user waits on snapshot I/O.
docker run --rm --network none hr-proxy:prepared python3 -c 'import boto3, cryptography'
cat > /etc/systemd/system/hr-agentd.service <<'UNIT'
[Unit]
Description=Harness Report disposable evaluation worker
After=docker.service network-online.target
Requires=docker.service
Wants=network-online.target
[Service]
Type=simple
WorkingDirectory=/opt/harness-report
EnvironmentFile=/etc/harness-report.env
ExecStartPre=/opt/hr-venv/bin/python /opt/harness-report/infra/runner-lifecycle.py ready
ExecStart=/opt/hr-venv/bin/python /opt/harness-report/hr-agentd --retire-after-job --idle-seconds 60
ExecStopPost=/opt/hr-venv/bin/python /opt/harness-report/infra/runner-lifecycle.py retire
TimeoutStartSec=1800
RuntimeMaxSec=${service_seconds}
TimeoutStopSec=120
KillMode=mixed
Restart=no
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now --no-block hr-agentd
