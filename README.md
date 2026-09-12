# Personal Data Exposure Auditor

**[Try it](https://footprint-auditor-ndkmuej5iq-lz.a.run.app)** · invite only.
The live instance is the real pipeline: gpt-oss-120b on Amazon Bedrock drives
the agent over real Brave search, and every invited person gets an account of
their own. Ask for the invite link. The first load waits a few seconds for a
cold start.

An app that helps a person find where **their own** data is exposed on the
public internet, and turns that into a prioritized plan to reduce it. One model
does the discovery and triage -- gpt-oss-120b on Bedrock, Claude Opus 5, or a
model running on your own machine. Everything that has to be right every time is
plain, tested code: who may be scanned, which URLs count as findings, whether
a page is about you or a namesake, and what the legal letters say.

## How it works

![Architecture: the React app (English and Finnish) talks to a FastAPI service with an ownership gate. It queues scans for a worker running the scan agent (gpt-oss-120b on Amazon Bedrock, Claude Opus 5 on Bedrock, Foundry or the Anthropic API, or a local model such as Qwen3 under Ollama), alongside the breach check and the action plan. Encrypted data goes to Postgres (SQLite in /tmp on the live instance), and each scan writes a content-free trace that the page streams while it runs. Outside APIs are Bedrock, Brave and Have I Been Pwned. It runs on Docker Compose locally, on Cloud Run for the live instance deployed by GitHub Actions, and has Terraform for ECS Fargate](docs/architecture.svg)

Only the purple box is AI. The model decides what to search for and judges which
pages are about you. Everything else is ordinary code: who may be scanned,
breach lookups, the action plan and its letters, and storage.

| Layer | Tech |
|---|---|
| Frontend | React 19, TypeScript, Vite; English and Finnish; served by FastAPI under a strict CSP |
| API | FastAPI, Python 3.12, Pydantic, JWT (PyJWT) with argon2 password hashing; invite codes and password reset |
| AI | A hand-written tool-use loop over one pluggable model: gpt-oss-120b on Amazon Bedrock (the live instance), Claude Opus 5 (Bedrock, Microsoft Foundry, Anthropic API), or any OpenAI-compatible endpoint, including a model running locally under Ollama |
| Outside data | Brave Search API, Have I Been Pwned API v3, GitHub and Bluesky public profile APIs |
| Storage | PostgreSQL 17 (SQLite in tests and on the live instance), SQLAlchemy 2 async, Alembic migrations, Fernet field encryption with HMAC blind indexes |
| Jobs | A separate scan worker claiming queued scans from the database |
| Observability | Per-scan trace with tokens, cost and latency, streamed to the page while the scan runs; optional OpenTelemetry export (GenAI conventions), content-free |
| Quality | pytest (164 tests), a nine-case agent eval with a CI gate, Playwright end-to-end tests, GitHub Actions |
| Runtime | Docker Compose locally; Cloud Run for the live instance, deployed from GitHub Actions through workload identity federation; Terraform for AWS (ECS Fargate, RDS, ALB), validated but not applied |

![The scan agent loop: the model chooses searches and judges pages; searches pass through ScopeGuard to Brave (or a fixture replay in evals), findings pass through record_finding, which checks claims against the page and sends text aimed at AI to review. Only a strong identifier puts a result straight into the plan; a name, even with a matching city, waits for This is me or Not me; a contradicting detail marks a namesake, counted and never saved](docs/scan-agent.svg)

The scan stage is an agent. The model picks a search, reads the results, decides
what to try next, judges each page, and stops when it has covered your
details. Its actions are deliberately narrow: it can search and record, and
the code in teal decides whether each action is allowed. It never sends
requests, fills in forms or reports accounts; those steps stay with you. You
can watch it work: the page streams the trace -- each search, each refused
query, each recorded page -- while the scan runs.

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
  requests, not controls. Names are compared token by token and without
  accents, so `Meikäläinen Maija` is still Maija Meikäläinen.
- `record_finding` only accepts `result_id`s that a tool returned during this
  scan, so a hallucinated or injected URL can't become a finding.
- 5 scans per account per day by default, one at a time, and an optional cap
  across the whole deployment; per-user and per-IP rate limits shared through
  the database, so they hold across replicas.
- Where `EA_REGISTRATION_CODE` is set, nobody can create an account without it.

### People with the same name

A result about someone who shares your name is noise, and it's also a
stranger's personal data, which this service shouldn't collect. Scans sort
every result in code ([`agent/orchestrator.py`](src/exposure_auditor/agent/orchestrator.py)
and [`agent/matching.py`](src/exposure_auditor/agent/matching.py)), not on the
model's word:

| The result shows | Outcome |
|---|---|
| your email, phone, username or photo | about you: straight into the plan |
| your name, even with a matching city, birth year or workplace | kept for your review, out of the plan until you decide |
| your name + a *contradicting* detail (another city, an age that doesn't fit) | a namesake: counted, **never stored** |
| text addressed to AI agents | never confident: waits for your review, whatever it seems to show |

A name plus a matching city used to count as a likely match. On the real web
that made a politician abroad and a restaurateur in the right city into
confident matches, because two people can share both, and a 160-character
snippet can mention a city that belongs to someone else. Now only a strong
identifier settles it; eval cases 08 and 09 keep it that way.

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
a name match against a bank ID / eID identity). Reverse-image search stays off
unless a TinEye key is set, for the same reason; see
[`tools/reverse_image.py`](src/exposure_auditor/tools/reverse_image.py).

## Does the agent work? Evals

[`evals/`](evals/README.md) holds nine cases: made-up people with small,
labelled webs of pages about them, pages about namesakes, and pages written to
mislead the agent. The eval runs the real agent and guards against a replay of
those pages and scores what it records: recall, precision of "likely"
findings, namesake leaks, guard interventions, cost and latency.

```bash
uv run exposure-auditor eval                                 # scripted model, free, runs in CI
uv run exposure-auditor eval --provider openai --repeat 3    # a real model, three runs: mean and range
```

It has failed its own gate twice, which is the point of having one. First, a
page addressed to the agent repeated the person's city, so the claim check
accepted it as a likely match; pages that talk to AI agents now always wait
for review. Later, a real scan returned namesakes in the right city as
confident matches while the suite still reported perfect precision, because
every fixture namesake lived somewhere else. Cases 08 and 09 reproduced it
(`namesake_leaks: 3`) and the strong-identifier rule fixed it.

The same cases run against any model. `gpt-oss-120b` on Bedrock measured best:
recall 0.969 across two runs of all nine cases, including the same-city
namesakes, no leaks, one refused claim a run, 25 s at p95 and about half a cent
a case. The local Qwen3 models were measured on the first seven cases: the 30B
mixture of experts lands between 0.72 and 1.0 depending on the session, and the
4B and 8B record almost nothing while producing claims the guards refuse, 24
and 78 a run. None of the guards depend on which model is driving. The tables
are in [`evals/README.md`](evals/README.md) and [`docs/design.md`](docs/design.md).

[`docs/design.md`](docs/design.md) explains the rest: why these models, what is
swappable, how it compares to DeleteMe and the people-search sites, what it
takes to run it on AWS with Bedrock, and how it is online for next to nothing.

[`docs/guardrails.md`](docs/guardrails.md) is the whole set as one contract:
every rule, the line that enforces it, the test or eval case that proves it,
and the ones that are still only structural.

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
  prompt. Choose the provider region to match your data-residency needs; the
  live instance calls Bedrock in `eu-central-1`.

## Architecture

```
React (web/) ──► FastAPI ── /auth (invite, reset), /identifiers, /scan (+ live trace), /findings, /breach-check, /remediation-plan
                    │
                    ├─ queues scans ──► worker (exposure-auditor worker)
                    │                     └─ ScanAgent: one model via llm.py
                    │                          Anthropic SDK: Claude on Bedrock | Foundry | Anthropic API
                    │                          OpenAI-compatible: gpt-oss-120b on Bedrock | Ollama locally
                    │                          tools: search_web (Brave) · reverse_image_search · record_finding
                    │                          every call through ScopeGuard + matching checks; every step traced
                    ├─ tools/hibp.py          breaches for verified emails + Pwned Passwords range
                    ├─ tools/profile_proof.py username bio proofs (GitHub, Bluesky)
                    └─ remediation/           deterministic plan + letters (GDPR en/fi, CCPA, general)
PostgreSQL or SQLite (Alembic) · field-level encryption · OpenTelemetry (optional)
```

Why a hand-written loop instead of Bedrock Agents or an agent framework: the
invariants above have to sit between the model and the tools, in code that's
tested and evaluated. The model provider is a setting, and the agent code is
identical for every one: Claude through the Anthropic SDK, or any
OpenAI-compatible endpoint through `openai_compat.py`, which translates the
message shape in both directions. Bedrock's OpenAI-compatible endpoint needed
no new code: the adapter written for Ollama serves it with a different base
URL and key. On the Anthropic API, refusal fallbacks are on
(`fallbacks: "default"`); nowhere else offers them server-side, so there a
refusal ends the scan as "refused".

## The live instance

What the invite link opens is the real pipeline, run as cheaply as it honestly
can be:

| | |
|---|---|
| Hosting | Cloud Run, `europe-north1`: one instance, scaled to zero, inside the free allowances |
| Model | `openai.gpt-oss-120b-1:0` on Amazon Bedrock (`eu-central-1`), OpenAI-compatible endpoint, $0.15 / $0.60 per million tokens |
| Search | Brave Search API, free tier |
| Accounts | Registration needs the invite code; every person gets an account of their own |
| Verification | No mail is sent: the code appears on the page |
| Storage | SQLite in the instance's `/tmp`, gone when it scales down |
| Caps | 12 searches and $0.25 per scan; 3 scans per account and 5 a day across the deployment |
| Deploy | After every green CI run on `main`, by GitHub Actions through workload identity federation; the job fails unless `/meta` reports a real model, real search and invite-only registration |

Two shortcuts keep it free, and each weakens something on purpose. Codes on the
page mean verification proves that someone holds the invite, not that they own
the address, so the ownership gate is reduced to "was invited". Storage in
`/tmp` means an account doesn't outlive the instance. Both are off by default
and production refuses them. Breach lookups are off there too, for want of an
HIBP key.

Why gpt-oss-120b rather than Claude: this AWS account isn't onboarded to
Bedrock's Messages API endpoint, where every Claude model id came back as
"does not exist", and the GPT-5.6 models need an entitlement from AWS Sales.
gpt-oss-120b was available, measured best of every model this project has
evaluated, and costs about half a cent a case.
[`deploy/cloudrun/BEDROCK.md`](deploy/cloudrun/BEDROCK.md) has the findings and
the setup.

Why separate accounts rather than one shared login: with real search, a shared
login would show every visitor the previous one's name, email and findings.

## Run it locally

```bash
uv sync
uv run python scripts/dev_env.py      # writes .env with generated keys
uv run exposure-auditor               # migrates, then serves http://127.0.0.1:8000
```

Locally, verification codes are printed to the server log instead of being
emailed. The app refuses to start with that setting when `EA_ENV=prod`. Other
commands: `exposure-auditor migrate`, `worker`, `check`, `stats` (latency and
cost across scans) and `eval`.

With `EA_DEMO_SCANS=true` (the local `.env` sets it), scans run the real
agent loop, guards, persistence and plan against synthetic
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
http://127.0.0.1:8000. It covers sign-up (with an invite code where the
instance asks for one, prefilled from `?invite=`), sign-in and password reset,
adding and verifying details (including username bio proofs and context
details), scans with a live trace and their cost, "This is me" / "Not me" on
results, breach and password checks, the action plan with its letters, and
account erasure. A header button switches between English and Finnish. In
Finnish, the plan and the model's explanations are in Finnish too, and Finnish
recipients get a Finnish GDPR letter. For hot reload, run
`uv run exposure-auditor` and `cd web && npm run dev` (http://localhost:5173).

Set `EA_DONATE_URL` to a PayPal donate or `paypal.me` link to show a
"Donate via PayPal" button. It's a plain link, so the strict CSP stays as it is.

## Run it for real: scanning yourself

Everything below runs on your own machine, against your own data.

**1. Get the keys.** A model provider is required, so is search; the breach key
is optional and only affects email lookups.

| What | Where | Cost |
|---|---|---|
| A model — one of: | | |
| **Local, under Ollama** | `EA_LLM_PROVIDER=ollama`; `ollama pull qwen3:30b-a3b-instruct-2507-q4_K_M` | free; needs ~20 GB of RAM |
| **Amazon Bedrock, OpenAI-compatible** (the live instance) | `EA_LLM_PROVIDER=openai`, `EA_OPENAI_BASE_URL=https://bedrock-runtime.<region>.amazonaws.com/openai/v1`, a Bedrock API key in `EA_OPENAI_API_KEY`, `EA_MODEL_ID=openai.gpt-oss-120b-1:0` | $0.15 / $0.60 per million tokens |
| Amazon Bedrock, Claude | `EA_LLM_PROVIDER=bedrock`, AWS credentials, `EA_BEDROCK_REGION`; `EA_BEDROCK_API=invoke` with an inference profile id (e.g. `eu.anthropic.claude-opus-5`) if the account isn't onboarded to Bedrock's Messages API endpoint | pay per token |
| Anthropic API | `EA_LLM_PROVIDER=anthropic`, `EA_ANTHROPIC_API_KEY` | pay per token |
| Microsoft Foundry | `EA_LLM_PROVIDER=foundry`, `EA_FOUNDRY_RESOURCE`, `EA_FOUNDRY_API_KEY` | pay per token |
| Any OpenAI-compatible API (Mistral, OpenAI, Groq, …) | `EA_LLM_PROVIDER=openai`, `EA_OPENAI_BASE_URL`, `EA_OPENAI_API_KEY`, `EA_MODEL_ID` | pay per token |
| Web search | `EA_BRAVE_API_KEY` | free tier: 1 query/second, 2,000/month |
| Email breach lookups | `EA_HIBP_API_KEY` | paid; password checks work without it |

Put them in `.env` and remove `EA_DEMO_SCANS`, which otherwise shows you
synthetic findings.

**On running the model locally.** A scan sends your name, email, phone and city
to whichever model judges the pages. With `EA_LLM_PROVIDER=ollama` that model is
on your machine, so those details never leave it — which is the behaviour you
would want from a tool whose whole subject is your exposure. It costs nothing
per scan, so you can run it as often as you like. It is also a smaller model,
and the eval is there to tell you what that costs you in recall and precision
rather than leaving it to taste.

**2. Check before you spend anything.**

```bash
uv run exposure-auditor check
```

One cheap call per dependency: the database, its migration revision and
whether the schema actually matches the models, a
16-token model call, a probe search, the breach endpoints, and the budget this
deployment will allow. It exits non-zero and names what's missing, so a wrong
region or an unapproved model fails here instead of halfway through a scan.

**3. Run the eval against the real model, before pointing it at yourself.**

```bash
uv run exposure-auditor eval --provider ollama --gate               # free, local
uv run exposure-auditor eval --provider openai --repeat 3 --gate    # or a hosted model
```

Nine cases against saved pages, so it costs model tokens and no search quota.
Run it for each model you are considering: same cases, same guards, and the
differences are measured rather than argued about. Answers vary between runs,
so `--repeat` reports the mean with the range and judges the invariants by the
worst run; `--language fi` runs the agent in Finnish. Set the `live:`
thresholds in `evals/thresholds.yaml` from what you measure.

**4. Then scan yourself.** Start the service, register, verify your email (the
code is printed to the log in dev), add what you want searched, and run a scan.
`uv run exposure-auditor stats` shows what each one cost.

### What it costs, and what stops it

A scan is bounded three ways, all in [config.py](src/exposure_auditor/config.py):

- `EA_AGENT_MAX_TURNS` (24) and `EA_AGENT_MAX_SEARCHES` (40) bound its shape.
- `EA_MAX_SCAN_COST_USD` (1.00) bounds its spend. The agent stops and
  summarizes what it has when the estimated running total passes the ceiling,
  so a loop that goes wrong costs a known amount. Set it to `null` to remove it.
  If a scan fails part-way, the findings it had already recorded are kept.
- `EA_SCANS_PER_DAY` (5) per account, one at a time, and
  `EA_SCANS_PER_DAY_TOTAL` (unset) across the deployment.

Set `EA_PRICE_INPUT_PER_MTOK` / `EA_PRICE_OUTPUT_PER_MTOK` to what your provider
actually bills; the defaults are Claude's, and the ceiling and the cost figures
both use these.

Searches are paced to Brave's free tier — one per second, rate-limit replies
retried — because the agent issues its tool calls in parallel and an unpaced
scan spends its search budget on refusals. On a paid tier, lower
`EA_SEARCH_MIN_INTERVAL_MS`.

## Tests

```bash
uv run exposure-auditor check                  # credentials and config, before a real scan
uv run pytest                                  # API, agent, guards, migrations, i18n
uv run exposure-auditor eval --gate            # agent eval (scripted)
cd web && npm run build && npx playwright test # end-to-end, starts its own API
```

CI (`.github/workflows/ci.yml`) runs lint, tests, the eval gate, the
end-to-end suite and a Docker build on every push. `deploy-demo.yml` deploys
the live instance once CI is green on `main`. `eval-live.yml` runs the eval
against a real model on demand.

## Deploy

- **Cloud Run** ([`deploy/cloudrun/`](deploy/cloudrun/README.md)) runs the live
  instance. `deploy-demo.yml` deploys the scripted demo by default; the
  repository variable `MODEL_PROVIDER=bedrock` switches it to the real,
  invite-only variant described above ([BEDROCK.md](deploy/cloudrun/BEDROCK.md)).
  Secrets live in Secret Manager, and GitHub authenticates through OIDC, so no
  Google key is stored anywhere.
- **AWS** ([`infra/`](infra/README.md)) is Terraform for a production shape:
  VPC, TLS-only load balancer, ECS Fargate services for the API and the worker,
  a one-off migration task, encrypted RDS PostgreSQL 17, Secrets Manager, and an
  OIDC role for the live eval. It has been validated, not applied.
- **Hugging Face Spaces** ([`deploy/huggingface/`](deploy/huggingface/)) is kept
  for accounts with PRO; the free tier no longer runs Docker Spaces.

## Not built yet

- **Identity assurance for names and photos.** See the residual risk above.
- **Mail and durable storage on the live instance.** Codes are shown on the
  page and accounts live in `/tmp`; a mail provider and a hosted Postgres would
  lift both.
- **A no-model baseline.** The fair question about any agent: how close do fixed
  query templates plus the same code rules get on the same nine cases? Not
  measured yet, so the eval can't answer it.
- **A website identifier.** You can't tell the app which domains are yours, so
  your own site, a namesake's and a domain you gave up years ago look alike.
- **Broker registry freshness.** Every entry is `last_verified: null`. Run
  `scripts/check_brokers.py`, confirm each procedure by hand, then date it.
- **Client-side refusal fallback on Bedrock and Foundry.** The SDK's refusal
  middleware isn't wired in yet.
- **Server messages are English.** Error texts from the API aren't translated.
