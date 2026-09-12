#!/usr/bin/env bash
# Store an AWS key pair for the deployed demo, and check it works first.
#
#   ./deploy/cloudrun/set-bedrock-key.sh [gcp-project-id]
#
# Prompts for both halves, hides what you type, never puts either on a command
# line, and drops them from the shell afterwards. Safe to re-run: it adds a new
# version to an existing secret rather than failing on a conflict.
set -euo pipefail

project="${1:-$(gcloud config get-value project 2>/dev/null)}"
[[ -n "$project" && "$project" != "(unset)" ]] || { echo "no gcp project: pass one as \$1" >&2; exit 1; }
number="$(gcloud projects describe "$project" --format='value(projectNumber)')"
region="${EA_BEDROCK_REGION:-eu-central-1}"

echo "project: $project"
echo
printf 'AWS access key ID (starts AKIA, 20 characters): '
read -rs key; echo
printf 'AWS secret access key (40 characters): '
read -rs secret; echo
echo

# Catch the two mistakes that waste an afternoon: the halves swapped, or a
# stray newline from a copy-paste.
key="${key//[$'\t\r\n ']}"
secret="${secret//[$'\t\r\n ']}"
[[ ${#key} -eq 20 ]] || echo "warning: an access key ID is usually 20 characters, this is ${#key}" >&2
[[ ${#secret} -eq 40 ]] || echo "warning: a secret access key is usually 40 characters, this is ${#secret}" >&2
[[ "$key" == AKIA* ]] || echo "warning: an access key ID usually starts with AKIA" >&2

if command -v aws >/dev/null 2>&1; then
  echo "checking the key against AWS..."
  if AWS_ACCESS_KEY_ID="$key" AWS_SECRET_ACCESS_KEY="$secret" AWS_DEFAULT_REGION="$region" \
     aws sts get-caller-identity --query Arn --output text; then
    echo "checking it can reach Bedrock in $region..."
    AWS_ACCESS_KEY_ID="$key" AWS_SECRET_ACCESS_KEY="$secret" AWS_DEFAULT_REGION="$region" \
      aws bedrock list-foundation-models --query "length(modelSummaries)" --output text 2>/dev/null ||
      echo "  (cannot list models: fine if the policy only allows InvokeModel)"
  else
    echo "that key pair was rejected by AWS; nothing was stored" >&2
    unset key secret
    exit 1
  fi
fi

for name in AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY; do
  gcloud secrets describe "$name" >/dev/null 2>&1 ||
    gcloud secrets create "$name" --replication-policy=automatic >/dev/null
  gcloud secrets add-iam-policy-binding "$name" \
    --member "serviceAccount:$number-compute@developer.gserviceaccount.com" \
    --role roles/secretmanager.secretAccessor >/dev/null
done

printf '%s' "$key"    | gcloud secrets versions add AWS_ACCESS_KEY_ID     --data-file=- >/dev/null
printf '%s' "$secret" | gcloud secrets versions add AWS_SECRET_ACCESS_KEY --data-file=- >/dev/null
unset key secret

echo
echo "stored. Then:"
echo "  gh variable set MODEL_PROVIDER --body bedrock"
echo "  gh variable set EA_BEDROCK_REGION --body $region"
echo "  gh workflow run deploy-demo"
