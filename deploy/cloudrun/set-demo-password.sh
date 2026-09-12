#!/usr/bin/env bash
# Generate the recruiter login for the hosted demo and store it as a secret.
#
#   ./deploy/cloudrun/set-demo-password.sh [gcp-project-id]
#
# The password in demo.py is public -- it is in a public repository -- so it
# cannot gate anything. This makes a new one, stores it in Secret Manager, and
# prints it once, here, for you to send to the people you choose. Run it again
# to rotate: the next deploy signs everyone out of the old password.
set -euo pipefail

project="${1:-$(gcloud config get-value project 2>/dev/null)}"
[[ -n "$project" && "$project" != "(unset)" ]] || { echo "no gcp project: pass one as \$1" >&2; exit 1; }
number="$(gcloud projects describe "$project" --format='value(projectNumber)')"

# Four words' worth of entropy in a shape people can read aloud and type.
password="$(python3 -c 'import secrets;print("-".join(secrets.token_urlsafe(6) for _ in range(4)))')"

gcloud secrets describe EA_DEMO_PASSWORD >/dev/null 2>&1 ||
  gcloud secrets create EA_DEMO_PASSWORD --replication-policy=automatic >/dev/null
printf '%s' "$password" | gcloud secrets versions add EA_DEMO_PASSWORD --data-file=- >/dev/null
gcloud secrets add-iam-policy-binding EA_DEMO_PASSWORD \
  --member "serviceAccount:$number-compute@developer.gserviceaccount.com" \
  --role roles/secretmanager.secretAccessor >/dev/null

cat <<OUT

Stored as EA_DEMO_PASSWORD in $project.

Recruiter login (takes effect on the next deploy):
  email:    demo@example.com
  password: $password

This is the only time it is shown. Send it to the people you choose; run this
script again to rotate it.
OUT
unset password
