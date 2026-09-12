#!/usr/bin/env bash
# One-time setup so GitHub Actions can deploy to Cloud Run without a key.
#
#   ./deploy/cloudrun/setup-github-oidc.sh <gcp-project-id> <github-owner/repo> [region]
#
# Prints the two values to paste into the repository's secrets.
set -euo pipefail

project="${1:?usage: $0 <gcp-project-id> <github-owner/repo>}"
repo="${2:?usage: $0 <gcp-project-id> <github-owner/repo>}"
pool="github"
provider="github-oidc"
account="github-deployer"

gcloud config set project "$project" >/dev/null
number="$(gcloud projects describe "$project" --format='value(projectNumber)')"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  iamcredentials.googleapis.com secretmanager.googleapis.com >/dev/null

gcloud iam service-accounts describe "$account@$project.iam.gserviceaccount.com" >/dev/null 2>&1 ||
  gcloud iam service-accounts create "$account" --display-name "GitHub Actions deployer" >/dev/null

# Enough to build and deploy this service, and nothing else.
for role in roles/run.admin roles/cloudbuild.builds.editor roles/artifactregistry.writer \
            roles/storage.admin roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding "$project" \
    --member "serviceAccount:$account@$project.iam.gserviceaccount.com" --role "$role" \
    --condition=None >/dev/null
done

# The running service reads the three secrets; the deployer only references them.
for name in EA_JWT_SECRET EA_FIELD_ENCRYPTION_KEY EA_BLIND_INDEX_KEY; do
  gcloud secrets describe "$name" >/dev/null 2>&1 || {
    case "$name" in
      EA_FIELD_ENCRYPTION_KEY) value="$(python3 -c 'import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())')" ;;
      *) value="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')" ;;
    esac
    printf '%s' "$value" | gcloud secrets create "$name" --data-file=- >/dev/null
    echo "created secret $name"
  }
  gcloud secrets add-iam-policy-binding "$name" \
    --member "serviceAccount:$number-compute@developer.gserviceaccount.com" \
    --role roles/secretmanager.secretAccessor >/dev/null
done

# A source deploy pushes into this repository. Creating it here means the
# deployer needs only writer, not the right to create repositories.
region="${3:-europe-north1}"
gcloud artifacts repositories describe cloud-run-source-deploy --location "$region" >/dev/null 2>&1 ||
  gcloud artifacts repositories create cloud-run-source-deploy --repository-format=docker \
    --location "$region" --description "Images built by Cloud Run source deploys" >/dev/null

gcloud iam workload-identity-pools describe "$pool" --location global >/dev/null 2>&1 ||
  gcloud iam workload-identity-pools create "$pool" --location global --display-name "GitHub" >/dev/null

gcloud iam workload-identity-pools providers describe "$provider" --location global --workload-identity-pool "$pool" >/dev/null 2>&1 ||
  gcloud iam workload-identity-pools providers create-oidc "$provider" \
    --location global --workload-identity-pool "$pool" \
    --issuer-uri "https://token.actions.githubusercontent.com" \
    --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository" \
    --attribute-condition "assertion.repository=='$repo'" >/dev/null

# Only this repository may impersonate the deployer.
gcloud iam service-accounts add-iam-policy-binding "$account@$project.iam.gserviceaccount.com" \
  --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/$number/locations/global/workloadIdentityPools/$pool/attribute.repository/$repo" >/dev/null

cat <<OUT

Add these to https://github.com/$repo/settings/secrets/actions

  GCP_WORKLOAD_IDENTITY_PROVIDER
    projects/$number/locations/global/workloadIdentityPools/$pool/providers/$provider

  GCP_DEPLOY_SERVICE_ACCOUNT
    $account@$project.iam.gserviceaccount.com

Optionally set the variable GCP_REGION (default europe-north1).
No key was created: GitHub proves who it is with a short-lived OIDC token.
OUT
