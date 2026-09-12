#!/usr/bin/env bash
# Generate the invite code recruiters register with, and store it as a secret.
#
#   ./deploy/cloudrun/set-invite-code.sh [gcp-project-id] [region]
#
# Everyone registers an account of their own -- a shared login would show each
# person the others' real details -- and the invite is what stops someone who
# merely found the URL from signing up. Prints the code and a ready-made link
# once, here. Run it again to rotate; the next deploy applies it.
set -euo pipefail

project="${1:-$(gcloud config get-value project 2>/dev/null)}"
region="${2:-europe-north1}"
[[ -n "$project" && "$project" != "(unset)" ]] || { echo "no gcp project: pass one as \$1" >&2; exit 1; }
number="$(gcloud projects describe "$project" --format='value(projectNumber)')"

code="$(python3 -c 'import secrets;print("-".join(secrets.token_urlsafe(5) for _ in range(3)))')"

gcloud secrets describe EA_REGISTRATION_CODE >/dev/null 2>&1 ||
  gcloud secrets create EA_REGISTRATION_CODE --replication-policy=automatic >/dev/null
printf '%s' "$code" | gcloud secrets versions add EA_REGISTRATION_CODE --data-file=- >/dev/null
gcloud secrets add-iam-policy-binding EA_REGISTRATION_CODE \
  --member "serviceAccount:$number-compute@developer.gserviceaccount.com" \
  --role roles/secretmanager.secretAccessor >/dev/null

url="$(gcloud run services describe footprint-auditor --region "$region" --format='value(status.url)' 2>/dev/null || true)"

cat <<OUT

Stored as EA_REGISTRATION_CODE in $project (takes effect on the next deploy).

Invite code: $code
Invite link: ${url:-<service url>}/?invite=$code

Shown only this once. Send the link; it fills the code in on the sign-up form.
OUT
unset code
