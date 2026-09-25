#!/usr/bin/env bash
# bootstrap.sh — the two things Terraform cannot do for itself.
#
#   ./bootstrap.sh state      create the S3 bucket Terraform keeps its state in
#   ./bootstrap.sh secrets    push the values from ../.env into Parameter Store
#   ./bootstrap.sh            both
#
# Everything else is `terraform apply`.  Run this once, from the laptop, with the operator profile:
#
#   AWS_PROFILE=operator ./bootstrap.sh
#   AWS_PROFILE=operator terraform init && AWS_PROFILE=operator terraform apply
#
# `secrets` creates the three SecureStrings as well as filling them, and is safe to re-run.  It does
# NOT depend on Terraform and can go either side of the first apply: Terraform deliberately does not
# manage these (api.tf says why), because a resource it manages is a resource it refreshes, and
# refreshing a SecureString means reading it — which the deploy role is denied.
set -euo pipefail

cd "$(dirname "$0")"

REGION="${AWS_REGION:-us-west-2}"
PROJECT="${HR_PROJECT:-harness-report}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="$PROJECT-tfstate-$ACCOUNT"

state() {
  if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
    echo "state bucket $BUCKET already exists"
    return
  fi
  echo "creating state bucket $BUCKET in $REGION"
  # us-east-1 is the one region that rejects an explicit LocationConstraint.
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"
  else
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
      --create-bucket-configuration "LocationConstraint=$REGION"
  fi
  # Versioning is the undo for a bad apply; the state file is the only copy of what exists.
  aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
  aws s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
  aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
    'BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true'
  echo "backend.tf must say: bucket = \"$BUCKET\""
}

# The three values Terraform is deliberately not allowed to hold — nor to know the existence of.
# Read out of ../.env, the same file run.sh and auth.py read, so there is one place they are
# written down.  put-parameter --overwrite creates the parameter when it is absent, so this is both
# the create and the update path.
secrets() {
  local env_file="../.env"
  [ -f "$env_file" ] || { echo "no $env_file — nothing to push"; return; }

  put() {
    local name="$1" value="$2"
    [ -n "$value" ] || { echo "  $name: empty in .env, left alone"; return; }
    aws ssm put-parameter --region "$REGION" --name "/$PROJECT/$name" \
      --type SecureString --value "$value" --overwrite \
      --description "harness-report: read by the API Lambda at cold start" >/dev/null
    echo "  $name: written to /$PROJECT/$name"
  }

  read_env() { grep -E "^$1=" "$env_file" | head -1 | cut -d= -f2- | sed "s/^['\"]//;s/['\"]$//"; }

  put GITHUB_CLIENT_SECRET "$(read_env GITHUB_CLIENT_SECRET)"
  put SESSION_SECRET       "$(read_env SESSION_SECRET)"

  # GITHUB_APP_KEY is a path on the laptop and the key itself in Parameter Store: the Lambda has no
  # ~/.ssh to put a .pem in, so handler.py writes it to /tmp at cold start.
  local key_path; key_path="$(read_env GITHUB_APP_KEY)"
  key_path="${key_path/#\~/$HOME}"
  if [ -n "$key_path" ] && [ -f "$key_path" ]; then
    put GITHUB_APP_KEY "$(cat "$key_path")"
  else
    echo "  GITHUB_APP_KEY: no readable .pem at '${key_path:-<unset>}', left alone"
  fi
}

case "${1:-all}" in
  state)   state ;;
  secrets) secrets ;;
  all)     state; echo; secrets ;;
  *)       echo "usage: $0 [state|secrets]" >&2; exit 2 ;;
esac
