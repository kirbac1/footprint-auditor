# Personal Data Exposure Auditor

An app that helps a person find where **their own** data is exposed on the
public internet, and turns that into a prioritized plan to reduce it. Claude
does the discovery and triage. Everything that has to be right every time is
plain, tested code: who may be scanned, which URLs count as findings, whether
a page is about you or a namesake, and what the legal letters say.

## How it works

![Architecture: the React app (English and Finnish) talks to a FastAPI service with an ownership gate. It queues scans for a worker running the scan agent (Claude Opus 5 on Bedrock, Foundry or the Anthropic API), alongside the breach check and the action plan. Encrypted data goes to Postgres managed with Alembic, and each scan writes a content-free trace exportable over OpenTelemetry. It runs on Docker Compose locally and on ECS Fargate through Terraform](docs/architecture.svg)

Only the purple box is AI. Claude decides what to search for and judges which
pages are about you. Everything else is ordinary code: who may be scanned,
breach lookups, the action plan and its letters, and storage.

| Layer | Tech |
|---|---|
| Frontend | React 19, TypeScript, Vite; English and Finnish; served by FastAPI under a strict CSP |
| API | FastAPI, Python 3.12, Pydantic, JWT (PyJWT) with argon2 password hashing |
| AI | Claude Opus 5 via the Anthropic Python SDK, on Amazon Bedrock, Microsoft Foundry or the Anthropic API; a hand-written tool-use loop |
| Outside data | Brave Search API, Have I Been Pwned API v3, GitHub and Bluesky public profile APIs |
| Storage | PostgreSQL 17 (SQLite in tests), SQLAlchemy 2 async, Alembic migrations, Fernet field encryption with HMAC blind indexes |
| Jobs | A separate scan worker claiming queued scans from the database |
| Observability | Per-scan trace with tokens, cost and latency; optional OpenTelemetry export (GenAI conventions), content-free |
| Quality | pytest (88 tests), an agent eval suite with a CI gate, Playwright end-to-end tests, GitHub Actions |
| Runtime | Docker Compose locally; AWS (ECS Fargate, RDS, ALB) with Terraform |

![The scan agent loop: Claude chooses searches and judges pages; searches pass through ScopeGuard to Brave (or a fixture replay in evals), findings pass through record_finding, which checks claims against the page and sends text aimed at AI to review, and results are sorted into about you, needs your review (This is me / Not me), or namesake](docs/scan-agent.svg)

The scan stage is an agent. Claude picks a search, reads the results, decides
what to try next, judges each page, and stops when it has covered your
details. Its actions are deliberately narrow: it can search and record, and
the code in teal decides whether each action is allowed. It never sends
requests, fills in forms or reports accounts; those steps stay with you.

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
characters of a SHA-1 (HIBP's k-anonymity range API); the comparison happens in
the browser.

## The ownership gate

A multi-tenant service that searches the web for a name, email, phone or photo
is a stalking tool unless it can only be pointed at yourself. The controls:

| Identifier | How it gets in scope |
|---|---|
| email, phone | **Verified**: a 6-digit code sent to it (10 min TTL, 5 attempts, resend capped) |
| username | **Verified**: a one-time code posted in the account's public GitHub or Bluesky bio; unproven usernames are never searched |
| name, photo | **Attested**: the user confirms it's theirs; capped per account (3 / 5) |
| city, birth year, workplace | **Context only**: used to tell the user apart from namesakes, never searched on their own |

Username proofs only support platforms with a public, login-free profile
API (GitHub, Bluesky). The check is one JSON request to a fixed host with
the handle in the path, so there's no scraping and no user-controlled
URL. Usernames on Instagram, X, TikTok or LinkedIn can't be proven yet.
`EA_ALLOW_UNPROVEN_USERNAMES=true` restores the old behaviour, where
attested usernames are searched too. A proven username doesn't open the
gate on its own, since it shows control of a profile, not of a contact point.

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
- 5 scans per account per day, one at a time; per-user and per-IP rate limits
  shared through the database, so they hold across replicas.

### People with the same name

A result about someone who shares your name is noise, and it's also a
stranger's personal data, which this service shouldn't collect. Scans sort
every result in code ([`agent/matching.py`](src/exposure_auditor/agent/matching.py)),
not on the model's word:

| The result shows | Outcome |
|---|---|
| your email, phone, username or photo | about you |
| your name + a matching context detail (city, birth year, workplace) | likely you |
| your name + a *contradicting* detail (another city, an age that doesn't fit) | a namesake: counted, **never stored** |
| only your name | kept for your review, and left out of the action plan until you decide |
| text addressed to AI agents | never "likely": it waits for your review, whatever it seems to show |

The model says which of your details a result shows; the code then checks
each claim against the URL, title and snippet the model saw, so it can't
invent a match. Emails and usernames match whole tokens only: `plaine` is not
`plaine88`. "This is me" moves a result into the plan. "Not me" deletes it and
records a blind index of the URL, so later scans skip it.

**Residual risk, stated plainly:** names and photos are attested, not proven.
Someone can verify their own email, then attest a stranger's name. The caps,
the verified-contact requirement, the daily limit and the audit log make that
slow and traceable, not impossible. Before opening sign-ups beyond people you
know, gate name and photo scans behind stronger identity assurance (for example,
a name match against a bank ID / eID identity). Reverse-image search ships with
no provider for the same reason; see [`tools/reverse_image.py`](src/exposure_auditor/tools/reverse_image.py).

## Does the agent work? Evals

[`evals/`](evals/README.md) holds seven cases: made-up people with small,
labelled webs of pages about them, pages about namesakes, and pages written to
mislead the agent. The eval runs the real agent and guards against a replay of
those pages and scores what it records: recall, precision of "likely"
findings, namesake leaks, guard interventions, cost and latency.

```bash
uv run exposure-auditor eval                         # scripted model, free, runs in CI
uv run exposure-auditor eval --provider anthropic    # a real model
```

Its first run failed the gate, which is the point of having one. A page
addressed to the agent happened to repeat the person's city, so the claim
check accepted it as a likely match. Now any page that talks to AI agents
stays in review. [`evals/README.md`](evals/README.md) has the details.

## Data handling

- PII columns (identifier values, account email, finding URLs and titles,
  rationales, letter drafts) are encrypted with Fernet at the field level, on
  top of disk encryption. Equality lookups use an HMAC blind index under a separate key.
- Scan traces carry model and tool names, outcome codes, timings and token
  counts, never queries, identifiers or page text. A trace with content would
  be an unencrypted second copy of the user's data.
- Logs carry ids, never values; scan failures log the exception *type* only.
- An append-only audit log records actions by id. It has no foreign key, so it
  survives account erasure as a pseudonymous trail.
- `DELETE /me` erases the account and everything tied to it.
- Identifiers go to the model in the conversation, never in the cached system
  prompt. Choose the provider region to match your data-residency needs.

## Architecture

```
React (web/) ──► FastAPI ── /auth, /identifiers, /scan, /findings, /breach-check, /remediation-plan
                    │
                    ├─ queues scans ──► worker (exposure-auditor worker)
                    │                     └─ ScanAgent: Claude via llm.py (Bedrock | Foundry | Anthropic API)
                    │                          tools: search_web (Brave) · reverse_image_search · record_finding
                    │                          every call through ScopeGuard + matching checks; every step traced
                    ├─ tools/hibp.py          breaches for verified emails + Pwned Passwords range
                    ├─ tools/profile_proof.py username bio proofs (GitHub, Bluesky)
                    └─ remediation/           deterministic plan + letters (GDPR en/fi, CCPA, general)
PostgreSQL (Alembic) · field-level encryption · OpenTelemetry (optional)
```

Why a hand-written loop instead of Bedrock Agents or an agent framework: the
invariants above have to sit between the model and the tools, in code that's
tested and evaluated. The model provider is a setting, and the agent code is
identical on all three. On the Anthropic API, refusal fallbacks are on
(`fallbacks: "default"`); Bedrock and Foundry don't offer them server-side,
so there a refusal ends the scan as "refused".

## Run it locally

```bash
uv sync
uv run python scripts/dev_env.py      # writes .env with generated keys
uv run exposure-auditor               # migrates, then serves http://127.0.0.1:8000
```

Locally, verification codes are printed to the server log instead of being
emailed. The app refuses to start with that setting when `EA_ENV=prod`. Other
commands: `exposure-auditor migrate`, `worker`, `stats` (latency and cost across
scans) and `eval`.

With `EA_DEMO_SCANS=true` (the local `.env` sets it), scans run the real
agent loop, guards, persistence and plan against a scripted model and synthetic
search results, so the whole UI works without any keys. Demo results are titled
`[DEMO]`, the UI shows a banner, and the app refuses to start in prod with it on.

### As a local service (Docker, Postgres)

The same shape as the AWS deployment: API, scan worker and Postgres,
restarting on their own, all reachable only from this machine.

```bash
docker compose up -d --build
docker compose logs -f api                   # verification codes show up here
docker compose --profile tracing up -d       # plus Jaeger at http://127.0.0.1:16686 (set EA_OTEL_ENABLED=true)
docker compose down                          # stop; add -v to also delete the database
```

### The web app

The React frontend is built into the image and served at
http://127.0.0.1:8000. It covers sign-up and sign-in, adding and verifying
details (including username bio proofs and context details), scans with a
per-scan trace and cost, "This is me" / "Not me" on results, breach and
password checks, the action plan with its letters, and account erasure. A
header button switches between English and Finnish. In Finnish, the plan and the
model's explanations are in Finnish too, and Finnish recipients get a Finnish
GDPR letter. For hot reload, run `uv run exposure-auditor` and
`cd web && npm run dev` (http://localhost:5173).

Set `EA_DONATE_URL` to a PayPal donate or `paypal.me` link to show a
"Donate via PayPal" button. It's a plain link, so the strict CSP stays as it is.

## Run it for real

Real scans need a model and a search API:

| Provider | Settings |
|---|---|
| Anthropic API | `EA_LLM_PROVIDER=anthropic`, `EA_ANTHROPIC_API_KEY` |
| Amazon Bedrock | `EA_LLM_PROVIDER=bedrock`, AWS credentials with Claude Opus 5 access, `EA_BEDROCK_REGION` |
| Microsoft Foundry | `EA_LLM_PROVIDER=foundry`, `EA_FOUNDRY_RESOURCE`, `EA_FOUNDRY_API_KEY` |

Plus `EA_BRAVE_API_KEY` for web search and, for email breach lookups, a paid
`EA_HIBP_API_KEY`. Remove `EA_DEMO_SCANS`, then run the eval against the real
model before scanning yourself; it needs only the model credentials:

```bash
uv run exposure-auditor eval --provider anthropic --gate
```

Set `EA_PRICE_INPUT_PER_MTOK` / `EA_PRICE_OUTPUT_PER_MTOK` to what your
provider bills, and the cost per scan will be right.

## Tests

```bash
uv run pytest                                  # API, agent, guards, migrations, i18n
uv run exposure-auditor eval --gate            # agent eval (scripted)
cd web && npm run build && npx playwright test # end-to-end, starts its own API
```

CI (`.github/workflows/ci.yml`) runs lint, tests, the eval gate, the
end-to-end suite and a Docker build on every push. `eval-live.yml` runs the
eval against a real model on demand.

## Deploy

[`infra/`](infra/README.md) is Terraform for AWS: VPC, TLS-only load balancer,
ECS Fargate services for the API and the worker, a one-off migration task,
encrypted RDS PostgreSQL 17, Secrets Manager, and an OIDC role for the live
eval. It has been validated, not applied.

## Not built yet

- **A live run.** The agent hasn't run against a real model yet (no
  credentials on the build machine); expect to tune the prompt against the eval.
- **Identity assurance for names and photos.** See the residual risk above.
- **Reverse-image provider.** Deliberately unset; see above.
- **Broker registry freshness.** Every entry is `last_verified: null`. Run
  `scripts/check_brokers.py`, confirm each procedure by hand, then date it.
- **Client-side refusal fallback on Bedrock and Foundry.** The SDK's refusal
  middleware isn't wired in yet.
- **Server messages are English.** Error texts from the API aren't translated.
