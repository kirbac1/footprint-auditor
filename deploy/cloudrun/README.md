# Deploying to Cloud Run

Two variants share one service name, one container and one workflow:

| | Scripted demo (default) | Real, invite-only (`MODEL_PROVIDER=bedrock`) |
|---|---|---|
| Model | scripted | gpt-oss-120b on Amazon Bedrock |
| Search | synthetic pages | Brave Search API |
| Accounts | a shared fictional person, open registration | invite code; an account per person |
| Verification codes | shown on the page | shown on the page |
| Storage | SQLite in `/tmp` | SQLite in `/tmp` |
| Cost | nothing | tokens, capped (see [BEDROCK.md](BEDROCK.md)) |

The live instance runs the real variant. [BEDROCK.md](BEDROCK.md) is its setup.

**Why Cloud Run.** Its free allowances (2M requests, 360k vCPU-seconds and 180k
GiB-seconds a month) are perpetual, it runs the same container as everything
else, and it scales to zero — an idle instance costs nothing. A billing account
is required; nothing is charged within the allowances. Set a budget alert
anyway.

## Deploying from GitHub (what the live instance uses)

[`setup-github-oidc.sh`](setup-github-oidc.sh) runs once. It creates a deployer
service account, the Artifact Registry repository, the three app secrets
(`EA_JWT_SECRET`, `EA_FIELD_ENCRYPTION_KEY`, `EA_BLIND_INDEX_KEY`), and a
workload identity pool scoped to one repository, then prints the two values to
paste into the repository's secrets:

```bash
./deploy/cloudrun/setup-github-oidc.sh <gcp-project-id> kirbac1/footprint-auditor
```

After that, [`deploy-demo.yml`](../../.github/workflows/deploy-demo.yml) deploys
on every green `ci` run on `main`, and on demand. No Google key is ever stored:
GitHub proves who it is with a short-lived OIDC token, and only that repository
may impersonate the deployer.

The workflow ends by reading `/meta` from the new revision and failing when the
deployment is not what it claims to be:

- the scripted demo fails if demo mode is off, since it would then show
  strangers real findings from a database in `/tmp`;
- the real variant fails if it reports the scripted model, demo search, or
  registration without an invite — each what a missing secret would silently
  produce.

## Deploying by hand (scripted demo only)

```bash
./deploy/cloudrun/deploy.sh <gcp-project-id> [region]
```

Enables the APIs, creates the three app secrets if they are missing, builds the
image with Cloud Build, and deploys the scripted demo with at most one instance.

## Scripts that store secrets

Each reads its value from `.env` or a hidden prompt, never from the command
line, tests it where it can, and adds a Secret Manager version. The next deploy
picks it up.

| Script | Secret | Used by |
|---|---|---|
| [`set-bedrock-api-key.sh`](set-bedrock-api-key.sh) | `EA_OPENAI_API_KEY` | real variant; one test call to the model first |
| [`set-brave-key.sh`](set-brave-key.sh) | `EA_BRAVE_API_KEY` | real variant; one test query first |
| [`set-invite-code.sh`](set-invite-code.sh) | `EA_REGISTRATION_CODE` | real variant; prints the code and invite link once |

## The trade-offs, stated

- **Cold starts.** Scaling to zero means the first request after an idle period
  waits for the container to start and the migrations to run — a few seconds.
- **The database is temporary.** SQLite lives in the instance's `/tmp`, which
  is memory, and disappears when the instance does. Nobody's account outlives
  the day. For anything lasting, attach a hosted Postgres and set
  `EA_DATABASE_URL`.
- **No mail.** Codes are shown on the page (`EA_CODES_ON_PAGE`, implied by demo
  mode). On the real variant that makes verification prove the invite rather
  than the address. Production refuses the setting.
- **One instance.** `--max-instances 1` keeps a single SQLite file coherent. It
  is also what keeps a surge inside the free tier.

**Opening it beyond invited people** needs mail delivery
(`EA_VERIFICATION_DELIVERY=aws`), durable Postgres, `EA_ENV=prod` and no codes
on the page — and then the last section of
[../../docs/design.md](../../docs/design.md): the remaining blockers are a
privacy notice, a retention schedule and processor agreements, not
infrastructure.
