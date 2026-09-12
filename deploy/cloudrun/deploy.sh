#!/usr/bin/env bash
# Deploy the demo to Google Cloud Run, inside the perpetual free tier.
#
#   ./deploy/cloudrun/deploy.sh <gcp-project-id> [region]
#
# Needs the gcloud CLI, a project with billing enabled (nothing is charged
# within the free allowances), and these APIs: run, cloudbuild, artifactregistry.
# The three secrets are generated once and stored in Secret Manager.
set -euo pipefail

project="${1:?usage: $0 <gcp-project-id> [region]}"
region="${2:-europe-north1}"           # Finland, and close to the user
service="footprint-auditor"
root="$(cd "$(dirname "$0")/../.." && pwd)"

gcloud config set project "$project" >/dev/null
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com >/dev/null

# One-time secrets. Rotating them invalidates existing demo accounts, which on
# a demo is no loss.
for name in EA_JWT_SECRET EA_FIELD_ENCRYPTION_KEY EA_BLIND_INDEX_KEY; do
  if ! gcloud secrets describe "$name" >/dev/null 2>&1; then
    case "$name" in
      EA_FIELD_ENCRYPTION_KEY) value="$(python3 -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')" ;;
      *) value="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')" ;;
    esac
    printf '%s' "$value" | gcloud secrets create "$name" --data-file=- >/dev/null
    echo "created secret $name"
  fi
done

gcloud run deploy "$service" \
  --source "$root" \
  --region "$region" \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 1 \
  --set-env-vars "EA_ENV=dev,EA_DEMO_SCANS=true,EA_VERIFICATION_DELIVERY=console,EA_DATABASE_URL=sqlite+aiosqlite:////tmp/footprint.db,EA_SCANS_PER_DAY=20" \
  --set-secrets "EA_JWT_SECRET=EA_JWT_SECRET:latest,EA_FIELD_ENCRYPTION_KEY=EA_FIELD_ENCRYPTION_KEY:latest,EA_BLIND_INDEX_KEY=EA_BLIND_INDEX_KEY:latest"

echo
echo "Scaled to zero when idle, one instance at most: the demo's SQLite file"
echo "lives in the instance's own /tmp and is gone when it scales down. That is"
echo "the intended trade -- no visitor's account outlives the day."
