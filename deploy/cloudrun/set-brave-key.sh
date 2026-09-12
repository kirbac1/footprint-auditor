#!/usr/bin/env bash
# Store the Brave Search key for the deployed instance, after proving it works.
#
#   ./deploy/cloudrun/set-brave-key.sh [gcp-project-id]
#
# Takes EA_BRAVE_API_KEY from this repository's .env when it is there, otherwise
# asks with a hidden prompt. The test query reads its token header from stdin,
# so the key is never a command-line argument, and a key Brave rejects is not
# stored. Safe to re-run: an existing secret gets a new version.
set -euo pipefail

root="$(cd "$(dirname "$0")/../.." && pwd)"
project="${1:-$(gcloud config get-value project 2>/dev/null)}"
[[ -n "$project" && "$project" != "(unset)" ]] || { echo "no gcp project: pass one as \$1" >&2; exit 1; }
number="$(gcloud projects describe "$project" --format='value(projectNumber)')"

key=""
if [[ -f "$root/.env" ]] && grep -q '^EA_BRAVE_API_KEY=' "$root/.env"; then
  key="$(grep '^EA_BRAVE_API_KEY=' "$root/.env" | tail -1 | cut -d= -f2-)"
  echo "using EA_BRAVE_API_KEY from .env"
fi
if [[ -z "$key" ]]; then
  printf 'Brave Search API key: '
  read -rs key
  echo
fi
key="${key//[$'\t\r\n ']}"
key="${key%\"}"; key="${key#\"}"

echo "checking the key with one query..."
status="$(printf 'X-Subscription-Token: %s\n' "$key" |
  curl -sS -o /dev/null -w '%{http_code}' -H @- -H 'Accept: application/json' \
    "https://api.search.brave.com/res/v1/web/search?q=example&count=1")"
if [[ "$status" != "200" ]]; then
  echo "Brave rejected the key (HTTP $status); nothing was stored" >&2
  unset key
  exit 1
fi

gcloud secrets describe EA_BRAVE_API_KEY >/dev/null 2>&1 ||
  gcloud secrets create EA_BRAVE_API_KEY --replication-policy=automatic >/dev/null
printf '%s' "$key" | gcloud secrets versions add EA_BRAVE_API_KEY --data-file=- >/dev/null
unset key
gcloud secrets add-iam-policy-binding EA_BRAVE_API_KEY \
  --member "serviceAccount:$number-compute@developer.gserviceaccount.com" \
  --role roles/secretmanager.secretAccessor >/dev/null

echo "stored as EA_BRAVE_API_KEY in $project."
