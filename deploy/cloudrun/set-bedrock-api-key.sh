#!/usr/bin/env bash
# Store a Bedrock API key for the deployed demo, after proving it can call the model.
#
#   ./deploy/cloudrun/set-bedrock-api-key.sh [gcp-project-id]
#
# Takes the key from this repository's .env (EA_OPENAI_API_KEY) when it is
# there, so it never has to be pasted again; otherwise asks with a hidden
# prompt. The key is never a command-line argument and never printed: the test
# call reads its Authorization header from stdin. A key that cannot call the
# model is not stored. Safe to re-run: an existing secret gets a new version.
set -euo pipefail

root="$(cd "$(dirname "$0")/../.." && pwd)"
project="${1:-$(gcloud config get-value project 2>/dev/null)}"
[[ -n "$project" && "$project" != "(unset)" ]] || { echo "no gcp project: pass one as \$1" >&2; exit 1; }
number="$(gcloud projects describe "$project" --format='value(projectNumber)')"
region="${EA_BEDROCK_REGION:-eu-central-1}"
model="${EA_MODEL_ID:-openai.gpt-oss-120b-1:0}"

key=""
if [[ -f "$root/.env" ]] && grep -q '^EA_OPENAI_API_KEY=' "$root/.env"; then
  key="$(grep '^EA_OPENAI_API_KEY=' "$root/.env" | tail -1 | cut -d= -f2-)"
  echo "using EA_OPENAI_API_KEY from .env"
fi
if [[ -z "$key" ]]; then
  printf 'Bedrock API key (starts ABSK): '
  read -rs key
  echo
fi
key="${key//[$'\t\r\n ']}"
key="${key%\"}"; key="${key#\"}"

echo "checking the key can call $model in $region..."
status="$(printf 'Authorization: Bearer %s\n' "$key" |
  curl -sS -o /dev/null -w '%{http_code}' -H @- -H 'Content-Type: application/json' \
    "https://bedrock-runtime.$region.amazonaws.com/openai/v1/chat/completions" \
    -d "{\"model\":\"$model\",\"max_tokens\":8,\"messages\":[{\"role\":\"user\",\"content\":\"say ok\"}]}")"
if [[ "$status" != "200" ]]; then
  echo "the key could not call the model (HTTP $status); nothing was stored" >&2
  unset key
  exit 1
fi

gcloud secrets describe EA_OPENAI_API_KEY >/dev/null 2>&1 ||
  gcloud secrets create EA_OPENAI_API_KEY --replication-policy=automatic >/dev/null
printf '%s' "$key" | gcloud secrets versions add EA_OPENAI_API_KEY --data-file=- >/dev/null
unset key
gcloud secrets add-iam-policy-binding EA_OPENAI_API_KEY \
  --member "serviceAccount:$number-compute@developer.gserviceaccount.com" \
  --role roles/secretmanager.secretAccessor >/dev/null

echo
echo "stored as EA_OPENAI_API_KEY in $project. Next:"
echo "  gh variable set MODEL_PROVIDER --body bedrock"
echo "  gh workflow run deploy-demo"
