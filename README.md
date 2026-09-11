# Personal Data Exposure Auditor

An API that helps a person find where **their own** data is exposed on the
public internet and turns that into a prioritized remediation plan. Claude on
Amazon Bedrock does the discovery and triage; everything that has to be
correct every time (who may be scanned, which URLs count as findings, what the
legal letters say) is plain code.

## What it does not do, by design

**It does not delete you from the internet.** No agent can. Most sites have no
deletion API; data brokers and people-search sites process removal requests
through human-run queues, often with identity checks only the person can pass.
So the output is a plan the user carries out: opt-out links, pre-filled GDPR /
CCPA letters, password-change and MFA items, impersonation reports. A
"remove everything in one click" feature is not on the roadmap. It can't be
built honestly, and automating identity verification on someone's behalf is
the wrong thing to be good at.

**It never sends anything on the user's behalf.** Letters are drafts.

**It never handles passwords.** The password check takes only the first 5 hex
characters of a SHA-1 (HIBP's k-anonymity range API); the comparison happens on
the client.

## The ownership gate

A multi-tenant service that searches the web for a name, email, phone or photo
is a stalking tool unless it can only be pointed at yourself. The controls:

| Identifier | How it gets in scope |
|---|---|
| email, phone | **Verified**: a 6-digit code sent to it (10 min TTL, 5 attempts, resend capped) |
| name, username, photo | **Attested**: the user confirms it's theirs; capped per account (3 / 5 / 5) |

- No scan or breach lookup runs until the account has at least one verified
  email or phone. Breach lookups only ever send verified emails to HIBP.
- Names must be at least first + last name; a single word would match half the internet.
- The agent's `search_web` tool rejects any query that doesn't contain an
  in-scope identifier, and rejects `OR`, `|` and `AROUND()`, which would
  otherwise let `"<me>" OR "<someone else>"` through. This is enforced in
  [`agent/scope.py`](src/exposure_auditor/agent/scope.py), not in the prompt.
  Search results are attacker-controllable text, so prompt instructions are
  requests, not controls.
- `record_finding` only accepts `result_id`s that a tool returned during this
  scan, so a hallucinated or injected URL can't become a finding.
- 5 scans per account per day, one at a time; per-user and per-IP rate limits.

### People with the same name

A result about someone who shares your name is noise, and it's also a
stranger's personal data, which this service shouldn't collect. Scans sort
every result into one of three buckets, in code
([`agent/matching.py`](src/exposure_auditor/agent/matching.py)), not on
the model's word:

| The result shows | Outcome |
|---|---|
| your email, phone, username or photo | about you |
| your name + a matching context detail (city, birth year, workplace) | likely you |
| your name + a *contradicting* detail (another city, an age that doesn't fit) | a namesake: counted, **never stored** |
| only your name | kept for your review, and left out of the action plan until you decide |

The model says which of your details a result shows; the code then checks
each claim against the URL, title and snippet the model saw, so it can't
invent a match. Context details are optional and are never searched for on
their own. "This is me" moves a result into the plan. "Not me" deletes it
and records a blind index of the URL, so later scans skip it.

**Residual risk, stated plainly:** names and photos are attested, not proven.
Someone can verify their own email, then attest a stranger's name. The caps,
the verified-contact requirement, the daily limit and the audit log make that
slow and traceable, not impossible. Before opening sign-ups beyond people you
know, gate name and photo scans behind stronger identity assurance (for example,
a name match against a payment or eID identity). Reverse-image search ships with
no provider for the same reason; see [`tools/reverse_image.py`](src/exposure_auditor/tools/reverse_image.py).

## Data handling

- PII columns (identifier values, account email, finding URLs/titles,
  rationales, letter drafts) are encrypted with Fernet at the field level, on top of
  disk encryption. Equality lookups use an HMAC blind index under a separate key.
- Logs carry ids, never values; scan failures log the exception *type* only.
- An append-only audit log records actions by id. It has no foreign key, so it
  survives account erasure as a pseudonymous trail.
- `DELETE /me` erases the account and everything tied to it.
- Identifiers go to Bedrock in the conversation, never in the cached system
  prompt. Pick a Bedrock region that matches your data-residency needs
  (default `eu-central-1`).

## Architecture

```
FastAPI  ── /auth, /identifiers, /scan, /impersonation-check, /breach-check, /remediation-plan
   │
   ├─ scans.py ──► ScanAgent (agent/orchestrator.py)
   │                 manual tool-use loop, Claude on Bedrock via AsyncAnthropicBedrockMantle
   │                 tools: search_web (Brave) · reverse_image_search (pluggable) · record_finding
   │                 every tool call passes through ScopeGuard
   ├─ tools/hibp.py          breachedaccount (verified emails) + Pwned Passwords range
   ├─ tools/brokers.py       broker registry (data/brokers.yaml): domains → opt-out routes
   └─ remediation/           deterministic plan builder + letter templates (GDPR / CCPA / general)
Postgres (SQLite locally) with field-level encryption
```

Why a hand-written loop instead of Bedrock Agents: the invariants above have to
sit between the model and the tools, in code we test. Bedrock has no
server-side web search, so search is our own tool.

## Run it locally

```bash
uv sync
uv run python scripts/dev_env.py      # writes .env with generated keys
uv run exposure-auditor               # http://127.0.0.1:8000/docs
```

Locally, verification codes are printed to the server log instead of being
emailed. The app refuses to start with that setting when `EA_ENV=prod`.

### As a local service (Docker, Postgres)

The same shape as the planned ECS + RDS deployment: the API container and
Postgres, restarting on their own, both reachable only from this machine.

```bash
uv run python scripts/dev_env.py      # once; also generates POSTGRES_PASSWORD
docker compose up -d --build
docker compose ps                     # both services should say (healthy)
docker compose logs -f api            # verification codes show up here
docker compose down                   # stop; add -v to also delete the database
```

The container has no AWS credentials, so scans report "not configured"
until you give it some (for example by mounting a read-only `~/.aws` and
setting `AWS_PROFILE`).

### The web app

The React frontend (`web/`, Vite + TypeScript) is built into the Docker
image and served by FastAPI at http://127.0.0.1:8000, on the same origin as
the API, with a strict Content-Security-Policy. It covers sign-up and sign-in,
adding and verifying your details, running scans and watching them finish, breach and
password checks, the action plan with its letters, and account erasure.

The password check hashes the password in the browser and sends only the first
5 characters of its SHA-1, so neither the password nor its hash reaches the server.

For frontend work with hot reload, run the API and Vite side by side; Vite
proxies API paths to port 8000:

```bash
uv run exposure-auditor               # API on :8000
cd web && npm install && npm run dev  # UI on http://localhost:5173
```

**Donate button.** Set `EA_DONATE_URL` in `.env` to your PayPal donate
link (from PayPal's "Donate button" setup, or a `paypal.me` link) and a
"Donate via PayPal" button appears in the header. It's a plain link rather
than PayPal's embedded button, so the strict CSP stays as it is. Only https
links on paypal.com or paypal.me are accepted.

**Demo scans.** With `EA_DEMO_SCANS=true` (the local `.env` sets it), scans
run the real agent loop, scope guard, persistence and plan against a scripted
model and synthetic search results, so the whole UI works without AWS. Every
demo result is titled `[DEMO]`, the UI shows a banner, and the app refuses to
start in prod with this on.

What works without any external accounts: sign-up, identifiers and
verification, the remediation plan, account erasure. For the rest:

| Feature | Needs |
|---|---|
| Scans | AWS credentials with Bedrock access to `anthropic.claude-opus-5` in `EA_BEDROCK_REGION`, plus `EA_BRAVE_API_KEY` for search |
| Breach check | `EA_HIBP_API_KEY` (paid HIBP key) |
| Password range check | nothing (Pwned Passwords is free) |

A typical session:

```bash
curl -X POST localhost:8000/auth/register -H 'content-type: application/json' \
  -d '{"email":"you@example.com","password":"a-long-password"}'
TOKEN=$(curl -s -X POST localhost:8000/auth/token -d 'username=you@example.com&password=a-long-password' | jq -r .access_token)
curl -X POST localhost:8000/identifiers -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"kind":"email","value":"you@example.com"}'
# read the code from the server log, then POST /identifiers/{id}/verify {"code": "..."}
curl -X POST localhost:8000/scan -H "authorization: Bearer $TOKEN"
curl localhost:8000/remediation-plan?jurisdiction=FI -H "authorization: Bearer $TOKEN"
```

## Tests

```bash
uv run pytest
uv run ruff check src tests
```

The tests run the whole API against SQLite, with a scripted stand-in for the
model and mocked HIBP and search. The test that matters most is
`test_exposure_scan_keeps_agent_in_scope_and_on_real_results`: the scripted
agent tries an out-of-scope query and a fabricated result id, and the test
checks that neither gets through.

## Not built yet

- **Deployment.** The Dockerfile runs as-is; the ECS Fargate service, RDS and
  Secrets Manager wiring (env vars injected into the task definition) don't
  exist yet.
- **Durable jobs.** Scans run as in-process background tasks. Production should
  move them to SQS plus a worker so a deploy doesn't kill a running scan.
- **Migrations.** Tables are created with `create_all` outside prod; add Alembic
  before the first production schema.
- **Shared rate limiting.** The limiter is per-process. Put it behind API
  Gateway usage plans or Redis when running more than one task.
- **Broker registry freshness.** Every entry is `last_verified: null`. Run
  `scripts/check_brokers.py`, confirm each procedure by hand, then date it.
  The plan tells users when a route hasn't been verified.
- **Reverse-image provider.** See above.
